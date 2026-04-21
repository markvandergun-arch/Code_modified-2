from __future__ import annotations

from typing import Optional, Tuple, List, Any

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from .profiles import LoadConfig
from . import gebouwmodel, pelektro, pprocess, pmobiliteit, poverig
from ..generation import simulate_pv, dispatch_wkk
from ..storage import simulate_battery, simulate_thermal_storage
from ..heat.heatpump import dispatch_heat_pump
from ..heat.boiler import dispatch_boiler
from ..heat.district_heat import dispatch_district_heat
from ..evaluation.grid import evaluate_grid, add_grid_evaluation_columns


# =============================================================================
# Index & plotting helpers
# =============================================================================
def make_year_index(
    year: int,
    *,
    freq: str = "15min",
    tz: str = "Europe/Amsterdam",
) -> pd.DatetimeIndex:
    start = pd.Timestamp(year=year, month=1, day=1, tz=tz)
    end = pd.Timestamp(year=year + 1, month=1, day=1, tz=tz)
    return pd.date_range(start=start, end=end, freq=freq, inclusive="left")


def _format_plot_time_axis(ax, index: pd.DatetimeIndex) -> None:
    if len(index) == 0:
        return
    span = index.max() - index.min()
    if span <= pd.Timedelta(days=3):
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    else:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.tick_params(axis="x", rotation=0)


def _resolve_simulation_index(
    *,
    year: int,
    freq: str,
    tz: str,
    weather: Optional[pd.DataFrame],
) -> pd.DatetimeIndex:
    if weather is None:
        raise ValueError(
            "De simulatie mag alleen draaien op weather data uit Excel. "
            "Een synthetische jaarindex is niet toegestaan."
        )
    if not isinstance(weather.index, pd.DatetimeIndex):
        raise TypeError("weather must have a DatetimeIndex")
    if weather.index.tz is None:
        return weather.index.tz_localize(tz, ambiguous=False, nonexistent="shift_forward")
    return weather.index


def _first_monday(year: int, month: int, tz: str) -> pd.Timestamp:
    d = pd.Timestamp(year=year, month=month, day=1, tz=tz)
    offset_days = (0 - d.dayofweek) % 7
    return d + pd.Timedelta(days=int(offset_days))


def select_week(index: pd.DatetimeIndex, *, year: int, month: int) -> pd.DatetimeIndex:
    if index.tz is None:
        raise ValueError("Index must be timezone-aware for consistent week selection.")
    tz = str(index.tz)
    start = _first_monday(year, month, tz)
    end = start + pd.Timedelta(days=7)
    return index[(index >= start) & (index < end)]


def find_peak_week(df: pd.DataFrame, column: str, *, window_days: int = 7) -> pd.DatetimeIndex:
    if column not in df.columns:
        raise KeyError(f"Column '{column}' not found in df.")
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise TypeError("df must have a DatetimeIndex.")
    if idx.tz is None:
        raise ValueError("df index must be timezone-aware.")
    if len(idx) < 2:
        return idx

    dt = idx[1] - idx[0]
    steps_per_day = max(int(pd.Timedelta(days=1) / dt), 1)
    window_len = max(int(window_days * steps_per_day), 1)

    values = df[column].to_numpy(dtype=float)
    best_i = 0
    best_peak = -np.inf
    for i in range(0, max(len(values) - window_len + 1, 1)):
        peak = np.nanmax(values[i : i + window_len])
        if peak > best_peak:
            best_peak = peak
            best_i = i
    return idx[best_i : best_i + window_len]


def plot_week(
    df: pd.DataFrame,
    week_index: pd.DatetimeIndex,
    *,
    grid_cap_kW: Optional[float] = None,
    title: str = "",
) -> plt.Figure:
    w = df.loc[week_index]
    comp_cols = [
        "P_heat_kW",
        "P_cool_kW",
        "P_elektro_kW",
        "P_process_kW",
        "P_mobility_kW",
        "P_overig_kW",
    ]
    comp_cols = [c for c in comp_cols if c in w.columns]
    comps = [np.clip(w[c].to_numpy(dtype=float), 0.0, None) for c in comp_cols]
    fig, ax = plt.subplots(figsize=(12, 4))
    if comp_cols:
        ax.stackplot(w.index, comps, labels=comp_cols, alpha=0.85)
    overlay_col = "P_load_total_kW" if "P_load_total_kW" in w.columns else "P_total_kW"
    if overlay_col in w.columns:
        ax.plot(w.index, w[overlay_col], linewidth=2.0, label=overlay_col)
    if "P_grid_import_kW" in w.columns:
        ax.plot(w.index, w["P_grid_import_kW"], linewidth=1.6, label="P_grid_import_kW")
    if grid_cap_kW is not None:
        ax.axhline(float(grid_cap_kW), linestyle="--", linewidth=1.5, label=f"Grid cap = {grid_cap_kW:.1f} kW")
    ax.set_title(title)
    ax.set_ylabel("kW")
    ax.grid(True, alpha=0.2)
    ax.legend(loc="upper right", ncol=3, fontsize=8)
    _format_plot_time_axis(ax, w.index)
    fig.tight_layout()
    return fig


def plot_energy_balance_week(
    df: pd.DataFrame,
    week_index: pd.DatetimeIndex,
    *,
    grid_cap_kW: Optional[float] = None,
    title: str = "Energy balance week",
) -> plt.Figure:
    w = df.loc[week_index]
    fig, ax = plt.subplots(figsize=(12, 4))
    for col in [
        "P_load_total_kW",
        "P_pv_kW",
        "P_wkk_el_kW",
        "P_hp_el_kW",
        "P_grid_import_kW",
        "P_grid_export_kW",
    ]:
        if col in w.columns:
            ax.plot(w.index, w[col], linewidth=1.8, label=col)
    if grid_cap_kW is not None:
        ax.axhline(float(grid_cap_kW), linestyle="--", linewidth=1.5, label=f"Grid cap = {grid_cap_kW:.1f} kW")
    ax.set_title(title)
    ax.set_ylabel("kW / kWth")
    ax.grid(True, alpha=0.2)
    ax.legend(loc="upper right", ncol=3, fontsize=8)
    _format_plot_time_axis(ax, w.index)
    fig.tight_layout()
    return fig


# =============================================================================
# Load components
# =============================================================================
def _run_load_components(
    config: LoadConfig,
    *,
    index: pd.DatetimeIndex,
    weather: Optional[pd.DataFrame] = None,
    include_debug: bool = False,
    pelektro_subloads: Optional[List[Any]] = None,
    pprocess_subloads: Optional[List[Any]] = None,
    poverig_subloads: Optional[List[Any]] = None,
) -> tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    if hasattr(gebouwmodel, "simulate_thermal_demand"):
        thermal_debug = gebouwmodel.simulate_thermal_demand(index, config.building, weather)
        P_heat_kW = thermal_debug["P_heat_kW"]
        P_cool_kW = thermal_debug["P_cool_kW"]
    else:
        P_heat_kW, P_cool_kW, thermal_debug = gebouwmodel.simulate(index, config.building, weather)
        thermal_debug = thermal_debug.copy()
        if "Q_heat_kWth" not in thermal_debug.columns:
            thermal_debug["Q_heat_kWth"] = P_heat_kW
        if "Q_cool_kWth" not in thermal_debug.columns:
            thermal_debug["Q_cool_kWth"] = P_cool_kW

    debug_df = thermal_debug if include_debug else None

    P_elektro_kW = pelektro.simulate(
        index,
        config.pelektro,
        bvo_m2=config.building.bvo_m2,
        subloads=pelektro_subloads,
        name="P_elektro_kW",
    )
    P_process_kW = pprocess.simulate(
        index,
        config.pprocess,
        subloads=pprocess_subloads,
        name="P_process_kW",
    )
    P_mobility_kW = pmobiliteit.simulate(index, config.pmobility, name="P_mobility_kW")
    P_overig_kW = poverig.simulate(
        index,
        config.poverig,
        bvo_m2=config.building.bvo_m2,
        subloads=poverig_subloads,
        name="P_overig_kW",
    )

    df = pd.DataFrame(
        {
            "P_heat_kW": P_heat_kW,
            "P_cool_kW": P_cool_kW,
            "Q_heat_kWth": thermal_debug["Q_heat_kWth"],
            "Q_cool_kWth": thermal_debug["Q_cool_kWth"],
            "P_elektro_kW": P_elektro_kW,
            "P_process_kW": P_process_kW,
            "P_mobility_kW": P_mobility_kW,
            "P_overig_kW": P_overig_kW,
        },
        index=index,
    )
    df["P_load_total_legacy_kW"] = (
        df["P_heat_kW"]
        + df["P_cool_kW"]
        + df["P_elektro_kW"]
        + df["P_process_kW"]
        + df["P_mobility_kW"]
        + df["P_overig_kW"]
    )
    df["P_electric_base_load_kW"] = (
        df["P_cool_kW"]
        + df["P_elektro_kW"]
        + df["P_process_kW"]
        + df["P_mobility_kW"]
        + df["P_overig_kW"]
    )
    df["P_load_total_kW"] = df["P_load_total_legacy_kW"]
    df["P_total_kW"] = df["P_load_total_kW"]
    return df, debug_df


# =============================================================================
# Dispatch helpers
# =============================================================================
def _series_or_zeros(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df.columns:
        return df[column].astype(float).fillna(0.0)
    return pd.Series(0.0, index=df.index, dtype=float)


def _resolve_heat_priority_mode(config: LoadConfig) -> str:
    mode = str(getattr(config.heat_system, "source_priority_mode", "prefer_hp_then_storage_then_boiler_then_dh") or "prefer_hp_then_storage_then_boiler_then_dh").strip().lower()
    aliases = {
        "min_grid_peak": "prefer_storage_then_hp_then_boiler_then_dh",
        "prefer_hp_then_boiler": "prefer_hp_then_storage_then_boiler_then_dh",
        "prefer_dh_then_boiler": "prefer_storage_then_dh_then_boiler_then_hp",
    }
    return aliases.get(mode, mode)


def _dispatch_firm_heat(index: pd.DatetimeIndex, config: LoadConfig, remaining_heat: pd.Series, *, priority_mode: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    boiler_input = pd.DataFrame({"Q_heat_unserved_after_hp_kWth": remaining_heat.astype(float)}, index=index)
    dh_input = pd.DataFrame({"Q_heat_unserved_after_boiler_kWth": remaining_heat.astype(float)}, index=index)

    if priority_mode == "prefer_storage_then_dh_then_boiler_then_hp":
        dh_df = dispatch_district_heat(index, config.district_heat, dh_input)
        boiler_input = pd.DataFrame({
            "Q_heat_unserved_after_hp_kWth": _series_or_zeros(dh_df, "Q_heat_unserved_after_dh_kWth")
        }, index=index)
        boiler_df = dispatch_boiler(index, config.boiler, boiler_input)
    else:
        boiler_df = dispatch_boiler(index, config.boiler, boiler_input)
        dh_input = pd.DataFrame({
            "Q_heat_unserved_after_boiler_kWth": _series_or_zeros(boiler_df, "Q_boiler_unserved_after_boiler_kWth")
        }, index=index)
        dh_df = dispatch_district_heat(index, config.district_heat, dh_input)

    return boiler_df, dh_df


def _compute_balance_checks(balance_df: pd.DataFrame, config: LoadConfig, *, grid_cap_kW: float | None) -> dict:
    checks: dict[str, object] = {}
    if balance_df.empty:
        return checks

    heat_tol = float(getattr(config.heat_system, "heat_balance_tolerance_kW", 1e-6))
    heat_residual = _series_or_zeros(balance_df, "heat_balance_residual_kWth")
    checks["heat_balance_max_abs_residual_kWth"] = float(heat_residual.abs().max())
    checks["heat_balance_within_tolerance"] = bool(heat_residual.abs().max() <= heat_tol)

    non_negative_cols = [
        "Q_heat_demand_total_kWth",
        "Q_heat_supply_total_kWth",
        "Q_heat_unserved_final_kWth",
        "F_total_fuel_kW",
        "F_total_gas_kW",
        "P_grid_import_kW",
        "P_grid_export_kW",
    ]
    negative_columns: list[str] = []
    for col in non_negative_cols:
        if col in balance_df.columns and float(balance_df[col].min()) < -1e-9:
            negative_columns.append(col)
    checks["non_physical_negative_columns"] = negative_columns
    checks["no_non_physical_negatives"] = len(negative_columns) == 0

    capacity_violations: dict[str, float] = {}
    if "P_hp_kW" in balance_df.columns:
        hp_cap = float(getattr(config.heat_pump, "power_el_kW", 0.0))
        if hp_cap > 0:
            capacity_violations["heat_pump_el_kW"] = float(max(balance_df["P_hp_kW"].max() - hp_cap, 0.0))
    if "P_wkk_el_kW" in balance_df.columns:
        wkk_cap = float(getattr(config.wkk, "power_el_kW", 0.0))
        if wkk_cap > 0:
            capacity_violations["wkk_el_kW"] = float(max(balance_df["P_wkk_el_kW"].max() - wkk_cap, 0.0))
    if "Q_heat_from_boiler_kWth" in balance_df.columns:
        boiler_cap = float(getattr(config.boiler, "power_th_kW", 0.0))
        if boiler_cap > 0:
            capacity_violations["boiler_th_kW"] = float(max(balance_df["Q_heat_from_boiler_kWth"].max() - boiler_cap, 0.0))
    if "Q_heat_from_dh_kWth" in balance_df.columns:
        dh_cap = float(getattr(config.district_heat, "power_th_kW", 0.0))
        if dh_cap > 0:
            capacity_violations["district_heat_th_kW"] = float(max(balance_df["Q_heat_from_dh_kWth"].max() - dh_cap, 0.0))
    checks["capacity_violations"] = capacity_violations
    checks["all_capacity_constraints_respected"] = all(v <= 1e-9 for v in capacity_violations.values())

    if grid_cap_kW is not None and "P_grid_import_kW" in balance_df.columns:
        checks["grid_contract_kW"] = float(grid_cap_kW)
        checks["peak_over_contract_kW"] = float(max(balance_df["P_grid_import_kW"].max() - float(grid_cap_kW), 0.0))

    return checks



# =============================================================================
# Public simulation APIs
# =============================================================================
def run_load_simulation(
    config: LoadConfig,
    *,
    year: int = 2024,
    freq: str = "15min",
    tz: str = "Europe/Amsterdam",
    weather: Optional[pd.DataFrame] = None,
    grid_cap_kW: Optional[float] = None,
    include_debug: bool = False,
    pelektro_subloads: Optional[List[Any]] = None,
    pprocess_subloads: Optional[List[Any]] = None,
    poverig_subloads: Optional[List[Any]] = None,
) -> Tuple[pd.DataFrame, plt.Figure, plt.Figure, Optional[pd.DataFrame]]:
    index = _resolve_simulation_index(year=year, freq=freq, tz=tz, weather=weather)
    df, debug_df = _run_load_components(
        config,
        index=index,
        weather=weather,
        include_debug=include_debug,
        pelektro_subloads=pelektro_subloads,
        pprocess_subloads=pprocess_subloads,
        poverig_subloads=poverig_subloads,
    )
    heat_peak_week = find_peak_week(df, "P_heat_kW", window_days=7)
    cool_peak_week = find_peak_week(df, "P_cool_kW", window_days=7)
    fig_heat = plot_week(df, heat_peak_week, grid_cap_kW=grid_cap_kW, title="Peak heating week")
    fig_cool = plot_week(df, cool_peak_week, grid_cap_kW=grid_cap_kW, title="Peak cooling week")
    return df, fig_heat, fig_cool, debug_df


def run_energy_system_simulation(
    config: LoadConfig,
    *,
    year: int = 2024,
    freq: str = "15min",
    tz: str = "Europe/Amsterdam",
    weather: Optional[pd.DataFrame] = None,
    grid_cap_kW: Optional[float] = None,
    include_debug: bool = False,
    pelektro_subloads: Optional[List[Any]] = None,
    pprocess_subloads: Optional[List[Any]] = None,
    poverig_subloads: Optional[List[Any]] = None,
) -> Tuple[pd.DataFrame, plt.Figure, plt.Figure, Optional[pd.DataFrame]]:
    index = _resolve_simulation_index(year=year, freq=freq, tz=tz, weather=weather)
    load_df, debug_df = _run_load_components(
        config,
        index=index,
        weather=weather,
        include_debug=include_debug,
        pelektro_subloads=pelektro_subloads,
        pprocess_subloads=pprocess_subloads,
        poverig_subloads=poverig_subloads,
    )

    balance_df = load_df.copy()
    if weather is not None and "T_amb_C" in weather.columns:
        balance_df["T_amb_C"] = weather["T_amb_C"].reindex(index).astype(float)

    pv_df = simulate_pv(index, config.pv, weather)
    balance_df = balance_df.join(pv_df, how="left")
    balance_df["P_pv_kW"] = balance_df["P_pv_kW"].fillna(0.0)

    balance_df["Q_space_heat_demand_kWth"] = balance_df["Q_heat_kWth"].clip(lower=0.0)
    balance_df["Q_heat_demand_total_kWth"] = balance_df["Q_space_heat_demand_kWth"]
    balance_df["Q_heat_demand_kWth"] = balance_df["Q_heat_demand_total_kWth"]
    balance_df["Q_cool_demand_kWth"] = balance_df["Q_cool_kWth"].clip(lower=0.0)
    balance_df["Q_heat_unserved_kWth"] = balance_df["Q_heat_demand_kWth"]
    balance_df["P_load_base_electric_kW"] = balance_df["P_electric_base_load_kW"]

    # Heat-first / electricity-aware dispatch backbone
    balance_df["P_residual_before_wkk_kW"] = np.clip(
        balance_df["P_load_base_electric_kW"] - balance_df["P_pv_kW"],
        0.0,
        None,
    )
    balance_df["P_export_headroom_kW"] = np.clip(
        balance_df["P_load_base_electric_kW"] - balance_df["P_pv_kW"],
        0.0,
        None,
    )

    wkk_df = dispatch_wkk(index, config.wkk, balance_df)
    balance_df = balance_df.join(wkk_df, how="left")
    balance_df["Q_heat_from_wkk_kWth"] = _series_or_zeros(balance_df, "Q_wkk_used_kWth")
    balance_df["Q_heat_unserved_after_wkk_kWth"] = np.clip(
        balance_df["Q_heat_demand_kWth"] - balance_df["Q_heat_from_wkk_kWth"],
        0.0,
        None,
    )
    balance_df["Q_heat_surplus_kWth"] = _series_or_zeros(balance_df, "Q_wkk_dumped_kWth")

    storage_input = pd.DataFrame({
        "Q_heat_surplus_kWth": balance_df["Q_heat_surplus_kWth"],
        "Q_heat_unserved_after_supply_kWth": balance_df["Q_heat_unserved_after_wkk_kWth"],
    }, index=index)
    thermal_df = simulate_thermal_storage(index, config.thermal_storage, storage_input)
    balance_df = balance_df.join(thermal_df, how="left")
    balance_df["Q_heat_from_storage_kWth"] = _series_or_zeros(balance_df, "Q_thermal_storage_discharge_kWth")
    balance_df["Q_heat_to_storage_kWth"] = _series_or_zeros(balance_df, "Q_thermal_storage_charge_kWth")
    balance_df["Q_heat_unserved_after_storage_kWth"] = _series_or_zeros(balance_df, "Q_heat_unserved_after_storage_kWth")

    base_net_after_wkk = (
        balance_df["P_load_base_electric_kW"]
        - balance_df["P_pv_kW"]
        - _series_or_zeros(balance_df, "P_wkk_el_kW")
    )
    if grid_cap_kW is not None:
        balance_df["P_contract_headroom_kW"] = np.clip(float(grid_cap_kW) - np.clip(base_net_after_wkk, 0.0, None), 0.0, None)
    else:
        balance_df["P_contract_headroom_kW"] = np.inf
    balance_df["P_grid_headroom_kW"] = balance_df["P_contract_headroom_kW"]

    hp_input = pd.DataFrame({
        "Q_heat_unserved_kWth": balance_df["Q_heat_unserved_after_storage_kWth"],
        "P_grid_headroom_kW": balance_df["P_grid_headroom_kW"],
        "P_contract_headroom_kW": balance_df["P_contract_headroom_kW"],
    }, index=index)
    if "T_amb_C" in balance_df.columns:
        hp_input["T_amb_C"] = balance_df["T_amb_C"]
    hp_df = dispatch_heat_pump(index, config.heat_pump, hp_input)
    balance_df = balance_df.join(hp_df, how="left")
    balance_df["Q_heat_from_hp_kWth"] = _series_or_zeros(balance_df, "Q_hp_th_kWth")
    balance_df["P_hp_kW"] = _series_or_zeros(balance_df, "P_hp_el_kW")

    remaining_after_hp = _series_or_zeros(balance_df, "Q_hp_unserved_after_hp_kWth")
    priority_mode = _resolve_heat_priority_mode(config)
    boiler_df, dh_df = _dispatch_firm_heat(index, config, remaining_after_hp, priority_mode=priority_mode)
    balance_df = balance_df.join(boiler_df, how="left")
    balance_df = balance_df.join(dh_df, how="left")
    balance_df["Q_heat_from_boiler_kWth"] = _series_or_zeros(balance_df, "Q_boiler_th_kWth")
    balance_df["Q_heat_from_dh_kWth"] = _series_or_zeros(balance_df, "Q_dh_th_kWth")

    if "Q_heat_unserved_after_dh_kWth" in balance_df.columns:
        final_unserved = balance_df["Q_heat_unserved_after_dh_kWth"]
    elif "Q_boiler_unserved_after_boiler_kWth" in balance_df.columns:
        final_unserved = balance_df["Q_boiler_unserved_after_boiler_kWth"]
    else:
        final_unserved = remaining_after_hp
    balance_df["Q_heat_unserved_final_kWth"] = np.clip(final_unserved, 0.0, None)
    balance_df["Q_heat_unserved_kWth"] = balance_df["Q_heat_unserved_final_kWth"]

    balance_df["Q_heat_supply_total_kWth"] = (
        balance_df["Q_heat_from_wkk_kWth"]
        + balance_df["Q_heat_from_storage_kWth"]
        + balance_df["Q_heat_from_hp_kWth"]
        + balance_df["Q_heat_from_boiler_kWth"]
        + balance_df["Q_heat_from_dh_kWth"]
    )
    balance_df["heat_balance_residual_kWth"] = (
        balance_df["Q_heat_demand_total_kWth"]
        - balance_df["Q_heat_supply_total_kWth"]
        - balance_df["Q_heat_unserved_final_kWth"]
        - balance_df["Q_heat_to_storage_kWth"]
        + balance_df["Q_heat_surplus_kWth"]
    )

    balance_df["F_total_fuel_kW"] = (
        _series_or_zeros(balance_df, "F_wkk_fuel_kW")
        + _series_or_zeros(balance_df, "F_boiler_fuel_kW")
    )
    balance_df["F_total_fuel_kWh_per_h"] = (
        _series_or_zeros(balance_df, "F_wkk_fuel_kWh_per_h")
        + _series_or_zeros(balance_df, "F_boiler_fuel_kWh_per_h")
    )
    balance_df["F_total_gas_kW"] = (
        _series_or_zeros(balance_df, "F_wkk_gas_kW")
        + _series_or_zeros(balance_df, "F_boiler_gas_kW")
    )
    balance_df["F_total_gas_kWh_per_h"] = (
        _series_or_zeros(balance_df, "F_wkk_gas_kWh_per_h")
        + _series_or_zeros(balance_df, "F_boiler_gas_kWh_per_h")
    )

    # Final electrical balance after heat decisions
    balance_df["P_load_total_kW"] = balance_df["P_load_base_electric_kW"] + balance_df["P_hp_kW"]
    balance_df["P_total_kW"] = balance_df["P_load_total_kW"]
    balance_df["P_generation_total_kW"] = balance_df[["P_pv_kW", "P_wkk_el_kW"]].sum(axis=1)
    balance_df["P_residual_before_battery_kW"] = balance_df["P_load_total_kW"] - balance_df["P_generation_total_kW"]
    balance_df["P_contract_limit_kW"] = float(grid_cap_kW) if grid_cap_kW is not None else np.nan

    battery_df = simulate_battery(index, config.battery, balance_df)
    balance_df = balance_df.join(battery_df, how="left")
    balance_df["P_residual_after_battery_kW"] = (
        balance_df["P_residual_before_battery_kW"]
        + balance_df["P_battery_charge_kW"]
        - balance_df["P_battery_discharge_kW"]
    )
    balance_df["P_residual_after_generation_kW"] = balance_df["P_residual_after_battery_kW"]
    balance_df["P_grid_import_before_battery_kW"] = np.clip(balance_df["P_residual_before_battery_kW"], 0.0, None)
    balance_df["P_grid_import_kW"] = np.clip(balance_df["P_residual_after_battery_kW"], 0.0, None)
    balance_df["P_grid_export_before_battery_kW"] = np.clip(-balance_df["P_residual_before_battery_kW"], 0.0, None)
    balance_df["P_grid_export_kW"] = np.clip(-balance_df["P_residual_after_battery_kW"], 0.0, None)
    balance_df["P_net_kW"] = balance_df["P_grid_import_kW"] - balance_df["P_grid_export_kW"]

    balance_df = add_grid_evaluation_columns(balance_df, grid_contract_kW=grid_cap_kW)
    balance_df["grid_cap_exceeded"] = balance_df["grid_contract_exceeded"]

    dt_h = (balance_df.index[1] - balance_df.index[0]).total_seconds() / 3600.0 if len(balance_df.index) > 1 else 1.0
    balance_df.attrs["kpis"] = {
        "peak_load_kW": float(balance_df["P_load_total_kW"].max()),
        "peak_grid_import_before_battery_kW": float(balance_df["P_grid_import_before_battery_kW"].max()),
        "peak_grid_import_kW": float(balance_df["P_grid_import_kW"].max()),
        "annual_load_kWh": float((balance_df["P_load_total_kW"] * dt_h).sum()),
        "annual_pv_kWh": float((balance_df["P_pv_kW"] * dt_h).sum()),
        "annual_wkk_el_kWh": float((balance_df["P_wkk_el_kW"] * dt_h).sum()),
        "annual_hp_el_kWh": float((balance_df["P_hp_kW"] * dt_h).sum()),
        "annual_grid_import_kWh": float((balance_df["P_grid_import_kW"] * dt_h).sum()),
        "annual_grid_export_kWh": float((balance_df["P_grid_export_kW"] * dt_h).sum()),
        "annual_battery_charge_kWh": float((balance_df["P_battery_charge_kW"] * dt_h).sum()),
        "annual_battery_discharge_kWh": float((balance_df["P_battery_discharge_kW"] * dt_h).sum()),
        "annual_heat_demand_kWhth": float((balance_df["Q_heat_demand_total_kWth"] * dt_h).sum()),
        "annual_heat_supply_kWhth": float((balance_df["Q_heat_supply_total_kWth"] * dt_h).sum()),
        "annual_heat_unserved_kWhth": float((balance_df["Q_heat_unserved_final_kWth"] * dt_h).sum()),
        "annual_wkk_heat_used_kWhth": float((balance_df["Q_heat_from_wkk_kWth"] * dt_h).sum()),
        "annual_storage_charge_kWhth": float((balance_df["Q_heat_to_storage_kWth"] * dt_h).sum()),
        "annual_storage_discharge_kWhth": float((balance_df["Q_heat_from_storage_kWth"] * dt_h).sum()),
        "annual_boiler_heat_kWhth": float((balance_df["Q_heat_from_boiler_kWth"] * dt_h).sum()),
        "annual_district_heat_kWhth": float((balance_df["Q_heat_from_dh_kWth"] * dt_h).sum()),
        "annual_fuel_input_kWh": float((balance_df["F_total_fuel_kWh_per_h"] * dt_h).sum()),
        "annual_gas_input_kWh": float((balance_df["F_total_gas_kWh_per_h"] * dt_h).sum()),
        "peak_heat_demand_kWth": float(balance_df["Q_heat_demand_total_kWth"].max()),
        "max_unserved_heat_kWth": float(balance_df["Q_heat_unserved_final_kWth"].max()),
    }

    grid_eval = evaluate_grid(
        balance_df,
        grid_contract_kW=grid_cap_kW,
        stoplight_thresholds=getattr(config.evaluation, "stoplight_thresholds", None),
        max_exceedance_duration_h=float(getattr(config.evaluation, "max_exceedance_duration_h", 0.0)),
        max_exceedance_energy_kWh=float(getattr(config.evaluation, "max_exceedance_energy_kWh", 0.0)),
        peak_percentiles=tuple(getattr(config.evaluation, "peak_percentiles", (0.95, 0.99))),
        robust_green_margin_fraction=float(getattr(config.evaluation, "robust_green_margin_fraction", 0.05)),
    )
    balance_df.attrs["grid_evaluation"] = grid_eval
    sanity_checks = _compute_balance_checks(balance_df, config, grid_cap_kW=grid_cap_kW)
    balance_df.attrs["sanity_checks"] = sanity_checks
    balance_df.attrs["consistency_checks"] = sanity_checks

    heat_peak_week = find_peak_week(balance_df, "Q_heat_demand_total_kWth", window_days=7)
    grid_peak_week = find_peak_week(balance_df, "P_grid_import_kW", window_days=7)
    fig_heat = plot_week(balance_df, heat_peak_week, grid_cap_kW=grid_cap_kW, title="Peak heating week")
    fig_balance = plot_energy_balance_week(
        balance_df,
        grid_peak_week,
        grid_cap_kW=grid_cap_kW,
        title="Peak grid-import week",
    )
    return balance_df, fig_heat, fig_balance, debug_df
