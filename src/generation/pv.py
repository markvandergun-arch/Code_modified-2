from __future__ import annotations

import numpy as np
import pandas as pd

def _reindex_weather(index: pd.DatetimeIndex, weather: pd.DataFrame | None) -> pd.DataFrame:
    if weather is None:
        raise ValueError("PV-simulatie vereist weather data uit Excel; weather=None is niet toegestaan.")

    if not isinstance(weather.index, pd.DatetimeIndex):
        raise TypeError("weather must have a DatetimeIndex")

    out = weather.copy().sort_index()

    if out.index.tz is None and index.tz is not None:
        out.index = out.index.tz_localize(index.tz, ambiguous=False, nonexistent="shift_forward")
    elif out.index.tz is not None and index.tz is not None:
        out.index = out.index.tz_convert(index.tz)

    # PV mag GEEN duplicates verwijderen of index aanpassen.
    # Als er duplicates zijn, moet dat upstream in read_weather_excel opgelost worden.
    if not out.index.is_unique:
        dupes = out.index[out.index.duplicated(keep=False)]
        raise ValueError(
            "Weather data bevat duplicate timestamps. "
            "Los dit op in read_weather_excel(); PV mag niets dedupliceren of interpoleren. "
            f"Aantal duplicate rows: {len(dupes)}"
        )

    if len(out) != len(index) or not out.index.equals(index):
        raise ValueError(
            "PV-simulatie vereist exact dezelfde index als weather data. "
            "Reindex/interpolatie is niet toegestaan."
        )

    if "ghi_Wm2" not in out.columns:
        raise KeyError("PV-simulatie vereist kolom 'ghi_Wm2' in weather data.")

    out["ghi_Wm2"] = pd.to_numeric(out["ghi_Wm2"], errors="coerce")
    if out["ghi_Wm2"].isna().any():
        raise ValueError("Kolom 'ghi_Wm2' bevat lege/ongeldige waarden; die mogen niet synthetisch worden aangevuld.")

    if "t_amb_C" in out.columns:
        out["t_amb_C"] = pd.to_numeric(out["t_amb_C"], errors="coerce")
        if out["t_amb_C"].isna().any():
            raise ValueError("Kolom 't_amb_C' bevat lege/ongeldige waarden; die mogen niet synthetisch worden aangevuld.")

    return out

def _orientation_factor(azimuth_deg: float) -> float:
    delta = abs(((float(azimuth_deg) - 180.0 + 180.0) % 360.0) - 180.0)
    return float(np.clip(1.0 - 0.4 * (delta / 180.0), 0.6, 1.0))


def _tilt_factor(tilt_deg: float) -> float:
    return float(np.clip(1.0 - abs(float(tilt_deg) - 35.0) / 120.0, 0.75, 1.05))


def simulate_pv(index: pd.DatetimeIndex, config, weather: pd.DataFrame | None = None) -> pd.DataFrame:
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a pandas.DatetimeIndex")
    if len(index) == 0:
        raise ValueError("index must not be empty")

    enabled = bool(getattr(config, "enabled", False))
    cap_kwp = float(getattr(config, "installed_capacity_kWp", 0.0))

    if (not enabled) or cap_kwp <= 0:
        return pd.DataFrame(
            {
                "P_pv_kW": np.zeros(len(index), dtype=float),
                "pv_irr_factor": np.zeros(len(index), dtype=float),
                "pv_temp_factor": np.ones(len(index), dtype=float),
                "ghi_Wm2": np.zeros(len(index), dtype=float),
            },
            index=index,
        )

    w = _reindex_weather(index, weather)
    ghi = np.clip(w["ghi_Wm2"].to_numpy(dtype=float), 0.0, None)
    has_t_amb = "t_amb_C" in w.columns
    if has_t_amb:
        t_amb = w["t_amb_C"].to_numpy(dtype=float)

    irr_factor = np.clip(ghi / 1000.0, 0.0, 1.5)
    orient = _orientation_factor(float(getattr(config, "azimuth_deg", 180.0)))
    tilt = _tilt_factor(float(getattr(config, "tilt_deg", 35.0)))
    pr = float(getattr(config, "performance_ratio", 0.85))
    inv_eff = float(getattr(config, "inverter_efficiency", 0.98))
    temp_coeff = float(getattr(config, "temp_coeff_per_C", -0.004))

    if has_t_amb:
        t_cell = t_amb + 0.03 * ghi
        temp_factor = np.clip(1.0 + temp_coeff * (t_cell - 25.0), 0.70, 1.10)
    else:
        temp_factor = np.ones(len(index), dtype=float)

    power = cap_kwp * irr_factor * orient * tilt * pr * inv_eff * temp_factor

    site_cap = getattr(config, "site_cap_kW", None)
    if site_cap is not None:
        power = np.minimum(power, float(site_cap))

    power = np.clip(power, 0.0, None)

    return pd.DataFrame(
        {
            "P_pv_kW": power.astype(float),
            "pv_irr_factor": irr_factor.astype(float),
            "pv_temp_factor": temp_factor.astype(float),
            "ghi_Wm2": ghi.astype(float),
        },
        index=index,
    )