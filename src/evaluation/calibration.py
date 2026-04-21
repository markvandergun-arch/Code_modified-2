from __future__ import annotations

import numpy as np
import pandas as pd


_ALLOWED_RESAMPLE_POLICIES = {"mean", "sum", "mean_to_hourly", "sum_to_hourly", "none"}


_CANONICAL_COMPARE_TARGETS = {
    "grid_import": ("P_grid_import_kW", "P_grid_import_kW"),
    "grid_export": ("P_grid_export_kW", "P_grid_export_kW"),
    "electric_load": ("P_load_total_kW", "P_electric_load_kW"),
    "gas": ("F_total_gas_kW", "F_gas_kW"),
    "heat": ("Q_heat_demand_total_kWth", "Q_heat_kWth"),
}


def calculate_calibration_metrics(
    simulated: pd.Series,
    measured: pd.Series,
    *,
    name: str = "grid_import",
) -> dict:
    """Calculate standard calibration metrics."""
    if not isinstance(simulated, pd.Series) or not isinstance(measured, pd.Series):
        raise TypeError("simulated and measured must be pandas Series")

    df = pd.concat([simulated.rename("sim"), measured.rename("meas")], axis=1).dropna()
    if df.empty:
        return {
            "name": name,
            "n_points": 0,
            "rmse": np.nan,
            "mae": np.nan,
            "mbe": np.nan,
            "nmbe_pct": np.nan,
            "cv_rmse_pct": np.nan,
            "r2": np.nan,
            "pearson_r": np.nan,
            "ashrae_hourly_pass": False,
            "ashrae_monthly_pass": False,
        }

    sim = df["sim"].astype(float)
    meas = df["meas"].astype(float)
    err = sim - meas
    rmse = float(np.sqrt(np.mean(np.square(err))))
    mae = float(np.mean(np.abs(err)))
    mbe = float(np.mean(err))
    meas_mean = float(np.mean(meas))
    nmbe = float(100.0 * mbe / meas_mean) if abs(meas_mean) > 1e-12 else np.nan
    cv_rmse = float(100.0 * rmse / meas_mean) if abs(meas_mean) > 1e-12 else np.nan
    pearson_r = float(sim.corr(meas)) if len(df) >= 2 else np.nan

    ss_res = float(np.sum(np.square(err)))
    ss_tot = float(np.sum(np.square(meas - np.mean(meas))))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 1e-12 else np.nan

    # Simple interpretation fields that are handy in the later validation UI.
    ashrae_hourly_pass = bool(abs(nmbe) <= 10.0 and cv_rmse <= 30.0) if np.isfinite(nmbe) and np.isfinite(cv_rmse) else False
    ashrae_monthly_pass = bool(abs(nmbe) <= 5.0 and cv_rmse <= 15.0) if np.isfinite(nmbe) and np.isfinite(cv_rmse) else False

    return {
        "name": name,
        "n_points": int(len(df)),
        "simulated_mean": float(np.mean(sim)),
        "measured_mean": meas_mean,
        "rmse": rmse,
        "mae": mae,
        "mbe": mbe,
        "nmbe_pct": nmbe,
        "cv_rmse_pct": cv_rmse,
        "r2": r2,
        "pearson_r": pearson_r,
        "ashrae_hourly_pass": ashrae_hourly_pass,
        "ashrae_monthly_pass": ashrae_monthly_pass,
    }



def align_measurements_to_simulation(
    simulation_df: pd.DataFrame,
    measurements_df: pd.DataFrame,
    *,
    sim_col: str,
    meas_col: str,
    resample_policy: str = "mean_to_hourly",
) -> pd.DataFrame:
    """Align measured and simulated series on a common timestamp index."""
    if resample_policy not in _ALLOWED_RESAMPLE_POLICIES:
        raise ValueError(f"Unsupported resample_policy='{resample_policy}'. Allowed: {sorted(_ALLOWED_RESAMPLE_POLICIES)}")
    if sim_col not in simulation_df.columns:
        raise KeyError(f"simulation_df must contain '{sim_col}'")
    if meas_col not in measurements_df.columns:
        raise KeyError(f"measurements_df must contain '{meas_col}'")

    sim = simulation_df[[sim_col]].copy()
    meas = measurements_df[[meas_col]].copy()

    if resample_policy == "mean_to_hourly":
        sim = sim.resample("1h").mean()
        meas = meas.resample("1h").mean()
    elif resample_policy == "sum_to_hourly":
        sim = sim.resample("1h").sum()
        meas = meas.resample("1h").sum()
    elif resample_policy == "mean":
        freq = pd.infer_freq(sim.index) or pd.infer_freq(meas.index)
        if freq is None:
            raise ValueError("Cannot infer a target frequency for resample_policy='mean'")
        sim = sim.resample(freq).mean()
        meas = meas.resample(freq).mean()
    elif resample_policy == "sum":
        freq = pd.infer_freq(sim.index) or pd.infer_freq(meas.index)
        if freq is None:
            raise ValueError("Cannot infer a target frequency for resample_policy='sum'")
        sim = sim.resample(freq).sum()
        meas = meas.resample(freq).sum()

    out = pd.concat([sim.rename(columns={sim_col: "simulated"}), meas.rename(columns={meas_col: "measured"})], axis=1)
    out = out.dropna(how="any")
    if not out.empty:
        out["residual"] = out["simulated"] - out["measured"]
        out["abs_residual"] = out["residual"].abs()
    return out



def compare_time_aggregations(aligned_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Build daily and monthly comparison tables from an aligned series."""
    if not {"simulated", "measured"}.issubset(aligned_df.columns):
        raise KeyError("aligned_df must contain 'simulated' and 'measured'")
    if not isinstance(aligned_df.index, pd.DatetimeIndex):
        raise TypeError("aligned_df must have a DatetimeIndex")

    hourly = aligned_df.copy().sort_index()
    daily = hourly[["simulated", "measured"]].resample("1D").mean().dropna(how="all")
    monthly = hourly[["simulated", "measured"]].resample("1ME").sum(min_count=1).dropna(how="all")

    for frame in (daily, monthly):
        if not frame.empty:
            frame["residual"] = frame["simulated"] - frame["measured"]
            frame["abs_residual"] = frame["residual"].abs()

    return {"hourly": hourly, "daily": daily, "monthly": monthly}



def summarize_peak_comparison(aligned_df: pd.DataFrame) -> dict:
    """Summarize absolute and relative peak differences."""
    if aligned_df.empty:
        return {
            "peak_simulated": np.nan,
            "peak_measured": np.nan,
            "peak_bias_kW": np.nan,
            "peak_bias_pct": np.nan,
            "timestamp_peak_simulated": None,
            "timestamp_peak_measured": None,
        }

    sim = aligned_df["simulated"].astype(float)
    meas = aligned_df["measured"].astype(float)
    peak_sim = float(sim.max())
    peak_meas = float(meas.max())
    peak_bias = peak_sim - peak_meas
    peak_bias_pct = 100.0 * peak_bias / peak_meas if abs(peak_meas) > 1e-12 else np.nan
    return {
        "peak_simulated": peak_sim,
        "peak_measured": peak_meas,
        "peak_bias_kW": float(peak_bias),
        "peak_bias_pct": float(peak_bias_pct) if np.isfinite(peak_bias_pct) else np.nan,
        "timestamp_peak_simulated": sim.idxmax().isoformat() if not sim.empty else None,
        "timestamp_peak_measured": meas.idxmax().isoformat() if not meas.empty else None,
    }



def prepare_validation_dataset(
    simulation_df: pd.DataFrame,
    measurements_bundle: dict[str, pd.DataFrame],
    *,
    comparison_mode: str = "grid_import",
    resample_policy: str = "mean_to_hourly",
) -> dict:
    """Build a complete validation payload for later use by the app/UI.

    Parameters
    ----------
    comparison_mode:
        One of: grid_import, grid_export, electric_load, gas, heat
    """
    if comparison_mode not in _CANONICAL_COMPARE_TARGETS:
        raise ValueError(f"Unsupported comparison_mode='{comparison_mode}'. Allowed: {sorted(_CANONICAL_COMPARE_TARGETS)}")
    if "measured_15m" not in measurements_bundle or "measured_hourly" not in measurements_bundle:
        raise KeyError("measurements_bundle must contain 'measured_15m' and 'measured_hourly'")

    sim_col, meas_col = _CANONICAL_COMPARE_TARGETS[comparison_mode]
    measurement_source = measurements_bundle["measured_hourly"] if "hourly" in resample_policy else measurements_bundle["measured_15m"]

    aligned = align_measurements_to_simulation(
        simulation_df,
        measurement_source,
        sim_col=sim_col,
        meas_col=meas_col,
        resample_policy=resample_policy,
    )
    aggregations = compare_time_aggregations(aligned)
    metrics_hourly = calculate_calibration_metrics(aggregations["hourly"]["simulated"], aggregations["hourly"]["measured"], name=f"{comparison_mode}_hourly") if not aggregations["hourly"].empty else calculate_calibration_metrics(pd.Series(dtype=float), pd.Series(dtype=float), name=f"{comparison_mode}_hourly")
    metrics_daily = calculate_calibration_metrics(aggregations["daily"]["simulated"], aggregations["daily"]["measured"], name=f"{comparison_mode}_daily") if not aggregations["daily"].empty else calculate_calibration_metrics(pd.Series(dtype=float), pd.Series(dtype=float), name=f"{comparison_mode}_daily")
    metrics_monthly = calculate_calibration_metrics(aggregations["monthly"]["simulated"], aggregations["monthly"]["measured"], name=f"{comparison_mode}_monthly") if not aggregations["monthly"].empty else calculate_calibration_metrics(pd.Series(dtype=float), pd.Series(dtype=float), name=f"{comparison_mode}_monthly")

    warnings: list[str] = []
    if aligned.empty:
        warnings.append("Geen overlap tussen simulatie en meetdata na alignment.")
    elif len(aligned) < 24:
        warnings.append("Weinig overlappende punten voor betrouwbare calibratie.")

    return {
        "comparison_mode": comparison_mode,
        "simulation_column": sim_col,
        "measurement_column": meas_col,
        "aligned": aligned,
        "aggregations": aggregations,
        "metrics": {
            "hourly": metrics_hourly,
            "daily": metrics_daily,
            "monthly": metrics_monthly,
        },
        "peak_summary": summarize_peak_comparison(aligned),
        "warnings": warnings,
    }
