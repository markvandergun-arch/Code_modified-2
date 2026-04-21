from __future__ import annotations

import numpy as np
import pandas as pd


_ALLOWED_WKK_DISPATCH_MODES = {
    "electricity_led",
    "thermal_led",
    "heat_led",
    "hybrid_peak_shaving",
    "heat_led_with_electric_cap",
    "must_run",
    "off",
}


def _get_required_series(demand_df: pd.DataFrame, candidates: list[str], *, fill_value: float = 0.0) -> np.ndarray:
    for col in candidates:
        if col in demand_df.columns:
            return demand_df[col].to_numpy(dtype=float)
    return np.full(len(demand_df.index), float(fill_value), dtype=float)


def _resolve_dispatch_mode(config) -> str:
    mode = str(getattr(config, "dispatch_mode", "electricity_led") or "electricity_led").strip().lower()
    if mode not in _ALLOWED_WKK_DISPATCH_MODES:
        raise ValueError(
            f"Unsupported WKK dispatch_mode='{mode}'. Allowed: {sorted(_ALLOWED_WKK_DISPATCH_MODES)}"
        )
    return mode


def dispatch_wkk(index: pd.DatetimeIndex, config, demand_df: pd.DataFrame) -> pd.DataFrame:
    """
    Dispatch a CHP/WKK with standardized electricity, heat, and fuel bookkeeping.

    Backward compatibility:
      - keeps function name/signature unchanged
      - still supports electricity-led peak shaving as default behaviour

    Expected optional demand columns:
      - P_residual_before_wkk_kW
      - P_load_total_kW
      - Q_heat_demand_kWth / Q_heat_kWth
      - Q_cool_demand_kWth / Q_cool_kWth  (currently not used for dispatch)

    Returned columns:
      - P_wkk_el_kW
      - P_wkk_th_kW
      - F_wkk_fuel_kW
      - F_wkk_fuel_kWh_per_h
      - F_wkk_gas_kW / F_wkk_gas_kWh_per_h
      - Q_wkk_available_kWth
      - Q_wkk_th_kWth
      - Q_wkk_used_kWth
      - Q_wkk_dumped_kWth
      - wkk_status
      - wkk_load_fraction
      - wkk_dispatch_mode
      - wkk_constraint_reason
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a pandas.DatetimeIndex")
    if not isinstance(demand_df, pd.DataFrame):
        raise TypeError("demand_df must be a pandas.DataFrame")
    if len(index) != len(demand_df.index):
        raise ValueError("index and demand_df must have the same length")

    enabled = bool(getattr(config, "enabled", False))
    p_rated = float(getattr(config, "p_rated_el_kW", 0.0))
    min_frac = float(getattr(config, "min_load_fraction", 0.0))
    el_eff = float(getattr(config, "electrical_efficiency", 0.40))
    th_eff = float(getattr(config, "thermal_efficiency", 0.45))
    mode = _resolve_dispatch_mode(config)

    if p_rated < 0:
        raise ValueError("config.p_rated_el_kW must be >= 0")
    if not (0.0 <= min_frac <= 1.0):
        raise ValueError("config.min_load_fraction must be between 0 and 1")
    if not (0.0 < el_eff <= 1.0):
        raise ValueError("config.electrical_efficiency must be between 0 and 1")
    if not (0.0 <= th_eff <= 1.0):
        raise ValueError("config.thermal_efficiency must be between 0 and 1")

    zeros = np.zeros(len(index), dtype=float)
    if (not enabled) or p_rated <= 0 or mode == "off":
        return pd.DataFrame({
            "P_wkk_el_kW": zeros,
            "P_wkk_th_kW": zeros,
            "Q_wkk_available_kWth": zeros,
            "Q_wkk_th_kWth": zeros,
            "Q_wkk_used_kWth": zeros,
            "Q_wkk_dumped_kWth": zeros,
            "F_wkk_fuel_kW": zeros,
            "F_wkk_fuel_kWh_per_h": zeros,
            "F_wkk_gas_kW": zeros,
            "F_wkk_gas_kWh_per_h": zeros,
            "wkk_status": zeros.astype(int),
            "wkk_load_fraction": zeros,
            "wkk_dispatch_mode": np.full(len(index), mode, dtype=object),
            "wkk_constraint_reason": np.full(len(index), "disabled", dtype=object),
        }, index=index)

    residual_el = _get_required_series(
        demand_df,
        ["P_residual_before_wkk_kW", "P_load_total_kW"],
        fill_value=0.0,
    )
    residual_el = np.clip(residual_el, 0.0, None)

    heat_demand = _get_required_series(
        demand_df,
        ["Q_heat_demand_kWth", "Q_heat_kWth"],
        fill_value=0.0,
    )
    heat_demand = np.clip(heat_demand, 0.0, None)

    # translate thermal demand to equivalent electric operating level when heat-led
    # P_el = Fuel * eta_el and Q_th = Fuel * eta_th => P_el = Q_th * eta_el / eta_th
    if th_eff > 0:
        p_required_for_heat = heat_demand * (el_eff / th_eff)
    else:
        p_required_for_heat = zeros.copy()

    export_headroom = _get_required_series(
        demand_df,
        ["P_export_headroom_kW", "P_wkk_export_headroom_kW", "P_residual_before_wkk_kW"],
        fill_value=np.inf,
    )
    export_headroom = np.where(np.isfinite(export_headroom), np.clip(export_headroom, 0.0, None), np.inf)

    constraint_reason = np.full(len(index), "none", dtype=object)

    if mode == "electricity_led":
        target_power = residual_el
        constraint_reason = np.where(residual_el <= 1e-9, "no_electric_need", "none")
    elif mode in {"thermal_led", "heat_led"}:
        target_power = p_required_for_heat
        constraint_reason = np.where(heat_demand <= 1e-9, "no_heat_need", "none")
    elif mode == "hybrid_peak_shaving":
        target_power = np.maximum(residual_el, p_required_for_heat)
        constraint_reason = np.where(
            np.maximum(residual_el, heat_demand) <= 1e-9,
            "no_heat_or_electric_need",
            np.where(residual_el >= p_required_for_heat, "electric_peak_shaving_priority", "heat_priority"),
        )
    elif mode == "heat_led_with_electric_cap":
        target_power = np.minimum(p_required_for_heat, export_headroom)
        constraint_reason = np.where(
            heat_demand <= 1e-9,
            "no_heat_need",
            np.where(target_power + 1e-9 < p_required_for_heat, "electric_cap", "none"),
        )
    elif mode == "must_run":
        target_power = np.full(len(index), p_rated, dtype=float)
        constraint_reason = np.full(len(index), "must_run", dtype=object)
    else:
        target_power = zeros.copy()
        constraint_reason = np.full(len(index), "off", dtype=object)

    power = np.minimum(np.clip(target_power, 0.0, None), p_rated)

    if min_frac > 0:
        min_power = p_rated * min_frac
        power = np.where(power >= min_power, power, 0.0)

    fuel = power / el_eff
    q_th = fuel * th_eff

    q_used = np.minimum(q_th, heat_demand)
    q_dumped = np.clip(q_th - q_used, 0.0, None)
    status = (power > 0).astype(int)
    load_fraction = np.where(p_rated > 0, power / p_rated, 0.0)

    out = pd.DataFrame({
        "P_wkk_el_kW": power.astype(float),
        "P_wkk_th_kW": q_th.astype(float),
        "Q_wkk_available_kWth": q_th.astype(float),
        "Q_wkk_th_kWth": q_th.astype(float),
        "Q_wkk_used_kWth": q_used.astype(float),
        "Q_wkk_dumped_kWth": q_dumped.astype(float),
        "F_wkk_fuel_kW": fuel.astype(float),
        "F_wkk_fuel_kWh_per_h": fuel.astype(float),
        "F_wkk_gas_kW": fuel.astype(float),
        "F_wkk_gas_kWh_per_h": fuel.astype(float),
        "wkk_status": status.astype(int),
        "wkk_load_fraction": load_fraction.astype(float),
        "wkk_dispatch_mode": np.full(len(index), mode, dtype=object),
        "wkk_constraint_reason": constraint_reason,
    }, index=index)

    return out
