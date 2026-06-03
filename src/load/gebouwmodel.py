# src/load/gebouwmodel.py
from __future__ import annotations

from dataclasses import asdict
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .profiles import BuildingArchetype, ORIENTATION_FACTOR_8

# Optional import (keeps this module robust if you temporarily run with older profiles.py)
try:
    from .profiles import Season
except Exception:  # pragma: no cover
    Season = None  # type: ignore


# =============================================================================
# Constants (simple, v1)
# =============================================================================

RHO_AIR_KG_M3 = 1.204  # ~20°C, sea level
CP_AIR_J_KG_K = 1006.0

SEC_PER_HOUR = 3600.0


# =============================================================================
# Helpers
# =============================================================================

def _ensure_weather(weather: Optional[pd.DataFrame], index: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Ensure weather dataframe exists and has the columns needed by the simplified model.

    Expected columns:
      - t_amb_C
      - wind_ms
      - ghi_Wm2
    """
    if weather is None:
        raise ValueError("Gebouwmodel vereist weather data uit Excel; weather=None is niet toegestaan.")

    # Maak altijd eerst een DataFrame-copy
    if isinstance(weather, pd.Series):
        weather = weather.to_frame()
    elif not isinstance(weather, pd.DataFrame):
        weather = pd.DataFrame(weather)

    weather = weather.copy()

    # Als timestamp nog als kolom aanwezig is, gebruik die als index
    if "timestamp" in weather.columns and not isinstance(weather.index, pd.DatetimeIndex):
        weather["timestamp"] = pd.to_datetime(weather["timestamp"], errors="coerce")
        weather = weather.dropna(subset=["timestamp"]).set_index("timestamp")

    # Probeer index alsnog naar DatetimeIndex te converteren
    if not isinstance(weather.index, pd.DatetimeIndex):
        try:
            converted_index = pd.to_datetime(weather.index, errors="coerce")
            keep = ~pd.isna(converted_index)
            weather = weather.loc[keep].copy()
            weather.index = pd.DatetimeIndex(converted_index[keep])
        except Exception as exc:
            raise TypeError(
                f"weather must have a DatetimeIndex, got {type(weather.index)}"
            ) from exc

    # Maak timezone consistent met simulatie-index
    if weather.index.tz is None and index.tz is not None:
        weather.index = weather.index.tz_localize(
            index.tz,
            ambiguous=False,
            nonexistent="shift_forward",
        )
    elif weather.index.tz is not None and index.tz is not None:
        weather.index = weather.index.tz_convert(index.tz)

    # Sorteer en verwijder dubbele timestamps
    weather = weather.sort_index()
    weather = weather[~weather.index.duplicated(keep="first")]

    if len(weather) != len(index) or not weather.index.equals(index):
        raise ValueError(
            "Gebouwmodel vereist exact dezelfde index als weather data. "
            "Reindex/interpolatie is niet toegestaan."
        )

    if "t_amb_C" not in weather.columns:
        raise KeyError("Gebouwmodel vereist kolom 't_amb_C' in weather data.")

    weather["t_amb_C"] = pd.to_numeric(weather["t_amb_C"], errors="coerce")
    if weather["t_amb_C"].isna().any():
        raise ValueError("Kolom 't_amb_C' bevat lege/ongeldige waarden; die mogen niet synthetisch worden aangevuld.")

    if "wind_ms" not in weather.columns and "wind_speed_mps" in weather.columns:
        weather["wind_ms"] = weather["wind_speed_mps"]

    if "wind_ms" in weather.columns:
        weather["wind_ms"] = pd.to_numeric(weather["wind_ms"], errors="coerce")
        if weather["wind_ms"].isna().any():
            raise ValueError("Kolom 'wind_ms' bevat lege/ongeldige waarden; die mogen niet synthetisch worden aangevuld.")

    if "ghi_Wm2" in weather.columns:
        weather["ghi_Wm2"] = pd.to_numeric(weather["ghi_Wm2"], errors="coerce")
        if weather["ghi_Wm2"].isna().any():
            raise ValueError("Kolom 'ghi_Wm2' bevat lege/ongeldige waarden; die mogen niet synthetisch worden aangevuld.")

    return weather

def _schedule_mask(index: pd.DatetimeIndex, days_active, start_hour: int, end_hour: int) -> np.ndarray:
    """
    Create a boolean mask (len=index) for a simple weekly schedule.

    days_active: iterable of weekday indices (Mon=0 .. Sun=6)
    start_hour inclusive, end_hour exclusive
    """
    dow = index.dayofweek.to_numpy()
    hour = index.hour.to_numpy()

    is_day = np.isin(dow, np.array(list(days_active), dtype=int))
    is_hour = (hour >= int(start_hour)) & (hour < int(end_hour))
    return is_day & is_hour


def _air_heat_flow_W(vdot_m3ph: np.ndarray, deltaT_K: np.ndarray) -> np.ndarray:
    """
    Sensible heat flow associated with air exchange.
    vdot_m3ph: volumetric flow [m³/h]
    deltaT_K : temperature difference [K]
    Returns heat flow [W].
    """
    vdot_m3ps = vdot_m3ph / SEC_PER_HOUR
    mdot = RHO_AIR_KG_M3 * vdot_m3ps  # kg/s
    return mdot * CP_AIR_J_KG_K * deltaT_K


def _ua_W_per_K(b: BuildingArchetype) -> float:
    """
    Envelope UA [W/K], purely transmission based on areas and U-values.
    """
    return (
        b.u_wall_W_m2K * b.a_wall_m2
        + b.u_roof_W_m2K * b.a_roof_m2
        + b.u_ground_W_m2K * b.a_ground_m2
        + b.u_window_W_m2K * b.a_window_m2
    )


def _month_to_season(month: int):
    """
    Simple meteorological seasons for NL context:
      - Winter: Dec/Jan/Feb
      - Spring: Mar/Apr/May
      - Summer: Jun/Jul/Aug
      - Autumn: Sep/Oct/Nov
    """
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def _seasonal_value_array(
    index: pd.DatetimeIndex,
    seasonal_map: Optional[dict],
    fallback_scalar: float,
) -> np.ndarray:
    """
    Build a per-timestep array from a seasonal mapping.
    seasonal_map may be keyed by Season Enum or strings (winter/spring/summer/autumn).
    """
    if not seasonal_map:
        return np.full(len(index), float(fallback_scalar), dtype=float)

    # normalize keys to lowercase strings
    norm: Dict[str, float] = {}
    for k, v in seasonal_map.items():
        if k is None:
            continue
        if hasattr(k, "value"):
            key = str(getattr(k, "value")).lower()
        else:
            key = str(k).lower()
        norm[key] = float(v)

    months = index.month.to_numpy()
    out = np.empty(len(index), dtype=float)
    for i, m in enumerate(months):
        s = _month_to_season(int(m))
        out[i] = float(norm.get(s, fallback_scalar))
    return out


def _get_setpoint_arrays(building: BuildingArchetype, occ: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Occupancy-aware setpoints (per timestep).

    If the new fields exist (t_*_occ_C / t_*_unocc_C), use them.
    Otherwise fall back to the legacy scalar fields (t_heat_set_C / t_cool_set_C).
    """
    # Use getattr so older configs still run
    t_heat_occ = getattr(building, "t_heat_set_occ_C", None)
    t_heat_unocc = getattr(building, "t_heat_set_unocc_C", None)
    t_cool_occ = getattr(building, "t_cool_set_occ_C", None)
    t_cool_unocc = getattr(building, "t_cool_set_unocc_C", None)

    if all(v is not None for v in (t_heat_occ, t_heat_unocc, t_cool_occ, t_cool_unocc)):
        T_heat_set = np.where(occ, float(t_heat_occ), float(t_heat_unocc)).astype(float)
        T_cool_set = np.where(occ, float(t_cool_occ), float(t_cool_unocc)).astype(float)
        return T_heat_set, T_cool_set

    # legacy fallback (scalar)
    return (
        np.full(len(occ), float(building.t_heat_set_C), dtype=float),
        np.full(len(occ), float(building.t_cool_set_C), dtype=float),
    )


# =============================================================================
# Public API
# =============================================================================
def simulate_thermal_demand(
    index: pd.DatetimeIndex,
    building: BuildingArchetype,
    weather: Optional[pd.DataFrame] = None,
    *,
    inf_base_factor: float = 1.0,
    inf_wind_factor_per_ms: float = 0.10,
    solar_proxy_factor: float = 0.85,
    deadband_C: float = 1.0,
) -> pd.DataFrame:
    """
    Explicit thermal-demand model.

    Returns a dataframe with thermal demand and derived electric-equivalent HVAC power.
    This becomes the new source of truth for later multi-energy-carrier balancing.

    Columns:
      - Q_heat_kWth / Q_cool_kWth: explicit thermal demand
      - P_heat_kW / P_cool_kW: temporary compatibility route based on COP/EER
      - regime / gains / weather diagnostics
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a pandas.DatetimeIndex")
    if len(index) == 0:
        raise ValueError("index must not be empty")

    w = _ensure_weather(weather, index)

    occ = _schedule_mask(
        index,
        building.occupancy_schedule.days_active,
        building.occupancy_schedule.start_hour,
        building.occupancy_schedule.end_hour,
    )

    T_amb = w["t_amb_C"].to_numpy(dtype=float)
    wind = w["wind_ms"].to_numpy(dtype=float) if "wind_ms" in w.columns else np.zeros(len(index), dtype=float)
    ghi = w["ghi_Wm2"].to_numpy(dtype=float) if "ghi_Wm2" in w.columns else np.zeros(len(index), dtype=float)

    T_heat_set, T_cool_set = _get_setpoint_arrays(building, occ)

    db2 = float(deadband_C) / 2.0
    heat_on = T_amb <= (T_heat_set - db2)
    cool_on = T_amb >= (T_cool_set + db2)

    both = heat_on & cool_on
    if np.any(both):
        cool_on = cool_on & ~both

    off = ~(heat_on | cool_on)

    UA = _ua_W_per_K(building)

    vdot_vent = np.where(occ, building.vdot_vent_m3ph_occ, building.vdot_vent_m3ph_unocc)
    vdot_inf_base_m3ph = building.qv10_m3ph_per_m2 * building.a_env_for_qv10_m2 * inf_base_factor
    vdot_inf = vdot_inf_base_m3ph * (1.0 + inf_wind_factor_per_ms * np.maximum(0.0, wind))

    q_int_W_m2 = np.where(occ, building.q_int_W_per_m2_occ, building.q_int_W_per_m2_unocc)
    Q_int_W = q_int_W_m2 * building.bvo_m2

    ori_fac = ORIENTATION_FACTOR_8[building.orientation]
    I_eff = ghi * solar_proxy_factor * ori_fac
    Q_sol_W = I_eff * building.a_window_m2 * building.g_value * building.shading_factor
    Q_gains_W = Q_int_W + Q_sol_W

    Q_heat_Wth = np.zeros(len(index), dtype=float)
    Q_cool_Wth = np.zeros(len(index), dtype=float)
    Q_trans_heat_W = np.zeros(len(index), dtype=float)
    Q_vent_heat_W = np.zeros(len(index), dtype=float)
    Q_inf_heat_W = np.zeros(len(index), dtype=float)
    Q_trans_cool_W = np.zeros(len(index), dtype=float)
    Q_vent_cool_W = np.zeros(len(index), dtype=float)
    Q_inf_cool_W = np.zeros(len(index), dtype=float)

    if np.any(heat_on):
        dT_heat = np.maximum(0.0, T_heat_set - T_amb)
        Q_trans_heat_W = UA * dT_heat
        Q_vent_heat_W = _air_heat_flow_W(vdot_vent, dT_heat) * (1.0 - building.eta_wtw)
        Q_inf_heat_W = _air_heat_flow_W(vdot_inf, dT_heat)
        Q_losses_heat_W = Q_trans_heat_W + Q_vent_heat_W + Q_inf_heat_W
        Q_heat_Wth = np.where(heat_on, np.maximum(0.0, Q_losses_heat_W - Q_gains_W), 0.0)

    if np.any(cool_on):
        dT_cool = np.maximum(0.0, T_amb - T_cool_set)
        Q_trans_cool_W = UA * dT_cool
        Q_vent_cool_W = _air_heat_flow_W(vdot_vent, dT_cool) * (1.0 - building.eta_wtw)
        Q_inf_cool_W = _air_heat_flow_W(vdot_inf, dT_cool)
        Q_env_air_gains_W = Q_trans_cool_W + Q_vent_cool_W + Q_inf_cool_W
        Q_cool_Wth = np.where(cool_on, np.maximum(0.0, Q_gains_W + Q_env_air_gains_W), 0.0)

    cop_arr = _seasonal_value_array(
        index=index,
        seasonal_map=getattr(building, "seasonal_cop_heat_by_season", None),
        fallback_scalar=float(building.cop_heat),
    )
    eer_arr = _seasonal_value_array(
        index=index,
        seasonal_map=getattr(building, "seasonal_eer_cool_by_season", None),
        fallback_scalar=float(building.eer_cool),
    )

    P_heat_kW = (Q_heat_Wth / 1000.0) / cop_arr
    P_cool_kW = (Q_cool_Wth / 1000.0) / eer_arr

    thermal_df = pd.DataFrame(
        {
            "occ": occ.astype(int),
            "regime_heat": heat_on.astype(int),
            "regime_cool": cool_on.astype(int),
            "regime_off": off.astype(int),
            "T_amb_C": T_amb,
            "wind_ms": wind,
            "ghi_Wm2": ghi,
            "T_heat_set_C": T_heat_set,
            "T_cool_set_C": T_cool_set,
            "UA_W_per_K": UA,
            "Q_int_W": Q_int_W,
            "Q_sol_W": Q_sol_W,
            "Q_gains_W": Q_gains_W,
            "Q_transmission_heat_W": Q_trans_heat_W,
            "Q_ventilation_heat_W": Q_vent_heat_W,
            "Q_infiltration_heat_W": Q_inf_heat_W,
            "Q_transmission_cool_W": Q_trans_cool_W,
            "Q_ventilation_cool_W": Q_vent_cool_W,
            "Q_infiltration_cool_W": Q_inf_cool_W,
            "Q_heat_Wth": Q_heat_Wth,
            "Q_cool_Wth": Q_cool_Wth,
            "Q_heat_kWth": Q_heat_Wth / 1000.0,
            "Q_cool_kWth": Q_cool_Wth / 1000.0,
            "cop_heat_eff": cop_arr,
            "eer_cool_eff": eer_arr,
            "P_heat_kW": P_heat_kW,
            "P_cool_kW": P_cool_kW,
        },
        index=index,
    )

    thermal_df.attrs["building"] = {
        "orientation": building.orientation.value,
        "deadband_C": float(deadband_C),
        "eta_wtw": float(building.eta_wtw),
        "bvo_m2": float(building.bvo_m2),
        "t_heat_set_C_legacy": float(getattr(building, "t_heat_set_C", np.nan)),
        "t_cool_set_C_legacy": float(getattr(building, "t_cool_set_C", np.nan)),
        "cop_heat_legacy": float(getattr(building, "cop_heat", np.nan)),
        "eer_cool_legacy": float(getattr(building, "eer_cool", np.nan)),
        "t_heat_set_occ_C": getattr(building, "t_heat_set_occ_C", None),
        "t_heat_set_unocc_C": getattr(building, "t_heat_set_unocc_C", None),
        "t_cool_set_occ_C": getattr(building, "t_cool_set_occ_C", None),
        "t_cool_set_unocc_C": getattr(building, "t_cool_set_unocc_C", None),
        "seasonal_cop_heat_by_season": getattr(building, "seasonal_cop_heat_by_season", None),
        "seasonal_eer_cool_by_season": getattr(building, "seasonal_eer_cool_by_season", None),
    }
    thermal_df.attrs["compatibility_mode"] = "thermal_demand_primary__electric_hvac_secondary"

    return thermal_df


def simulate(
    index: pd.DatetimeIndex,
    building: BuildingArchetype,
    weather: Optional[pd.DataFrame] = None,
    *,
    inf_base_factor: float = 1.0,
    inf_wind_factor_per_ms: float = 0.10,
    solar_proxy_factor: float = 0.85,
    deadband_C: float = 1.0,
) -> Tuple[pd.Series, pd.Series, pd.DataFrame]:
    """
    Backward-compatible wrapper.

    Current callers still expect:
      (P_heat_kW, P_cool_kW, debug_df)

    Internally, the model is now thermal-demand-first. The returned dataframe contains
    both explicit thermal demand (Q_*_kWth) and temporary electric-equivalent HVAC load
    (P_*_kW) so later steps can migrate gradually.
    """
    thermal_df = simulate_thermal_demand(
        index=index,
        building=building,
        weather=weather,
        inf_base_factor=inf_base_factor,
        inf_wind_factor_per_ms=inf_wind_factor_per_ms,
        solar_proxy_factor=solar_proxy_factor,
        deadband_C=deadband_C,
    )

    s_heat = thermal_df["P_heat_kW"].rename("P_heat_kW")
    s_cool = thermal_df["P_cool_kW"].rename("P_cool_kW")
    return s_heat, s_cool, thermal_df
