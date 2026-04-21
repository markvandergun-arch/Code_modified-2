from __future__ import annotations

import numpy as np
import pandas as pd


DEFAULT_GRID_EVAL_PERCENTILES: tuple[float, ...] = (0.95, 0.99)


def evaluate_grid(
    df: pd.DataFrame,
    *,
    grid_contract_kW: float | None,
    stoplight_thresholds: dict | None = None,
    max_exceedance_duration_h: float = 0.0,
    max_exceedance_energy_kWh: float = 0.0,
    peak_percentiles: tuple[float, ...] | None = None,
    robust_green_margin_fraction: float = 0.05,
) -> dict:
    """Evaluate grid performance and stoplight status for a timeseries.

    Expected columns:
      - P_grid_import_kW
      - optionally P_grid_export_kW
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas.DataFrame")
    if "P_grid_import_kW" not in df.columns:
        raise KeyError("df must contain 'P_grid_import_kW'")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("df must have a DatetimeIndex")

    dt_h = _dt_hours(df.index)
    s_import = df["P_grid_import_kW"].astype(float).clip(lower=0.0)
    s_export = df["P_grid_export_kW"].astype(float).clip(lower=0.0) if "P_grid_export_kW" in df.columns else pd.Series(0.0, index=df.index)

    percentiles = tuple(peak_percentiles or DEFAULT_GRID_EVAL_PERCENTILES)
    percentile_values = {
        f"p{int(round(p * 100))}_grid_import_kW": float(s_import.quantile(float(p)))
        for p in percentiles
    }

    peak_import = float(s_import.max())
    annual_import_kWh = float((s_import * dt_h).sum())
    annual_export_kWh = float((s_export * dt_h).sum())
    import_hours = float((s_import > 0).sum() * dt_h)
    export_hours = float((s_export > 0).sum() * dt_h)

    out = {
        "peak_grid_import_kW": peak_import,
        "annual_grid_import_kWh": annual_import_kWh,
        "annual_grid_export_kWh": annual_export_kWh,
        "hours_with_grid_import": import_hours,
        "hours_with_grid_export": export_hours,
        "dt_hours": dt_h,
        **percentile_values,
    }

    thresholds = dict(stoplight_thresholds or {})

    if grid_contract_kW is None or grid_contract_kW <= 0:
        out.update(
            {
                "grid_contract_kW": None,
                "contract_exceedance_hours": None,
                "contract_exceedance_energy_kWh": None,
                "contract_exceedance_peak_kW": None,
                "worst_continuous_exceedance_h": None,
                "peak_ratio_to_contract": None,
                "robust_green_limit_kW": None,
                "stoplight": "unknown",
                "used_stoplight_thresholds": thresholds,
            }
        )
        return out

    contract = float(grid_contract_kW)
    exceedance = (s_import - contract).clip(lower=0.0)
    exceedance_mask = exceedance > 0
    exceedance_hours = float(exceedance_mask.sum() * dt_h)
    exceedance_energy = float((exceedance * dt_h).sum())
    exceedance_peak = float(exceedance.max())
    longest_run_steps = _longest_true_run(exceedance_mask.to_numpy(dtype=bool))
    worst_continuous_exceedance_h = float(longest_run_steps * dt_h)

    peak_ratio = peak_import / contract if contract > 0 else np.nan
    p99_value = percentile_values.get("p99_grid_import_kW", peak_import)
    p99_ratio = p99_value / contract if contract > 0 else np.nan
    robust_green_limit_kW = contract * max(0.0, 1.0 - float(robust_green_margin_fraction))
    robust_green_ratio = robust_green_limit_kW / contract if contract > 0 else np.nan

    green_peak_ratio_max = float(thresholds.get("green_peak_ratio_max", robust_green_ratio))
    orange_peak_ratio_max = float(thresholds.get("orange_peak_ratio_max", 1.00))
    orange_p99_ratio_max = float(thresholds.get("orange_p99_ratio_max", green_peak_ratio_max))

    if (
        peak_ratio <= green_peak_ratio_max
        and p99_ratio <= orange_p99_ratio_max
        and exceedance_hours <= float(max_exceedance_duration_h)
        and exceedance_energy <= float(max_exceedance_energy_kWh)
    ):
        stoplight = "green"
    elif peak_ratio <= orange_peak_ratio_max:
        stoplight = "orange"
    else:
        stoplight = "red"

    out.update(
        {
            "grid_contract_kW": contract,
            "contract_exceedance_hours": exceedance_hours,
            "contract_exceedance_energy_kWh": exceedance_energy,
            "contract_exceedance_peak_kW": exceedance_peak,
            "worst_continuous_exceedance_h": worst_continuous_exceedance_h,
            "peak_ratio_to_contract": peak_ratio,
            "p99_ratio_to_contract": p99_ratio,
            "robust_green_limit_kW": robust_green_limit_kW,
            "stoplight": stoplight,
            "used_stoplight_thresholds": thresholds,
        }
    )
    return out


def add_grid_evaluation_columns(df: pd.DataFrame, *, grid_contract_kW: float | None) -> pd.DataFrame:
    """Return a copy of df with per-timestep contract exceedance diagnostics added."""
    if "P_grid_import_kW" not in df.columns:
        raise KeyError("df must contain 'P_grid_import_kW'")

    out = df.copy()
    out["P_grid_contract_kW"] = np.nan if grid_contract_kW is None else float(grid_contract_kW)
    if grid_contract_kW is None or grid_contract_kW <= 0:
        out["P_grid_contract_excess_kW"] = 0.0
        out["grid_contract_exceeded"] = 0
        return out

    out["P_grid_contract_excess_kW"] = (out["P_grid_import_kW"].astype(float) - float(grid_contract_kW)).clip(lower=0.0)
    out["grid_contract_exceeded"] = (out["P_grid_contract_excess_kW"] > 0).astype(int)
    return out


def find_worst_grid_week(df: pd.DataFrame, *, window_days: int = 7, score_column: str = "P_grid_contract_excess_kW") -> pd.DatetimeIndex:
    """Select the worst week for grid stress.

    Prefers exceedance energy if available, otherwise falls back to peak import.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("df must have a DatetimeIndex")
    if len(df.index) < 2:
        return df.index

    if score_column in df.columns:
        score = df[score_column].astype(float).clip(lower=0.0)
    elif "P_grid_import_kW" in df.columns:
        score = df["P_grid_import_kW"].astype(float).clip(lower=0.0)
    else:
        raise KeyError("df must contain either score_column or 'P_grid_import_kW'")

    dt = df.index[1] - df.index[0]
    steps_per_day = max(int(pd.Timedelta(days=1) / dt), 1)
    window_len = max(int(window_days * steps_per_day), 1)
    values = score.to_numpy(dtype=float)

    best_i = 0
    best_score = -np.inf
    for i in range(0, max(len(values) - window_len + 1, 1)):
        window = values[i : i + window_len]
        current = float(np.nansum(window))
        if current > best_score:
            best_score = current
            best_i = i
    return df.index[best_i : best_i + window_len]


def build_grid_duration_curve(df: pd.DataFrame, *, contract_kW: float | None) -> pd.DataFrame:
    if "P_grid_import_kW" not in df.columns:
        raise KeyError("df must contain 'P_grid_import_kW'")
    s = df["P_grid_import_kW"].astype(float).clip(lower=0.0).sort_values(ascending=False).reset_index(drop=True)
    dt_h = _dt_hours(df.index) if isinstance(df.index, pd.DatetimeIndex) else 1.0
    duration_h = (np.arange(len(s), dtype=float) + 1.0) * dt_h
    out = pd.DataFrame({
        "duration_h": duration_h,
        "P_grid_import_kW": s.to_numpy(dtype=float),
    })
    out["P_grid_contract_kW"] = np.nan if contract_kW is None else float(contract_kW)
    out["P_grid_contract_excess_kW"] = 0.0 if contract_kW is None else np.clip(out["P_grid_import_kW"] - float(contract_kW), 0.0, None)
    return out


def _longest_true_run(mask: np.ndarray) -> int:
    longest = 0
    current = 0
    for flag in mask:
        if bool(flag):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def _dt_hours(index: pd.DatetimeIndex) -> float:
    if len(index) <= 1:
        return 1.0
    return (index[1] - index[0]).total_seconds() / 3600.0
