from __future__ import annotations

from pathlib import Path
import pandas as pd
import streamlit as st
import altair as alt

import io
import json
import zipfile

from src.load import (
    BuildingType,
    YearClass,
    Orientation8,
    BuildingShape,
    SHAPE_FACTOR_BY_SHAPE,
    WeeklySchedule,
    make_default_load_config,
    run_load_simulation,
    run_energy_system_simulation,
)
from src.load.weather import read_weather_excel
from src.load.total import find_peak_week
from src.evaluation.grid import evaluate_grid, find_worst_grid_week, build_grid_duration_curve
from src.evaluation.calibration import prepare_validation_dataset
from src.io.measurements import load_measurement_bundle
from src.generation import simulate_pv, dispatch_wkk

st.set_page_config(page_title="Energiesysteem Prototype", layout="wide")
st.title("Energiesysteem Prototype")
st.caption("Structuur: Load · Generation · Storage · Total. De simulatie gebruikt één kunstmatig jaar opgebouwd uit de Excel-maanden.")

APP_DIR = Path(__file__).resolve().parent
WEATHER_PATH = APP_DIR / "Weatherdata 2008-2021.xlsx"
SIM_FREQ = None
TZ = "Europe/Amsterdam"
DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_TO_INT = {d: i for i, d in enumerate(DAY_LABELS)}


def init_state() -> None:
    defaults = {
        "pelektro_subloads": [],
        "pprocess_subloads": [],
        "poverig_subloads": [],
        "def_building_type": BuildingType.OFFICE.value,
        "def_year_class": YearClass.Y2015_PLUS.value,
        "def_orientation": Orientation8.S.value,
        "def_bvo": 2500.0,
        "def_floors": 1,
        "def_wwr": 0.35,
        "def_shape": BuildingShape.RECTANGULAR.value,
        "def_manual_shape": False,
        "def_shape_manual": 1.0,
        "grid_cap_kW": 50.0,
        "pv_enabled": True,
        "pv_cap": 250.0,
        "pv_tilt": 35.0,
        "pv_azimuth": 180.0,
        "pv_pr": 0.85,
        "pv_inv_eff": 0.98,
        "pv_temp_coeff": -0.004,
        "pv_site_cap": 0.0,
        "wkk_enabled": False,
        "wkk_p_rated": 150.0,
        "wkk_min_frac": 0.0,
        "wkk_el_eff": 0.40,
        "wkk_th_eff": 0.45,
        "bat_enabled": False,
        "bat_capacity": 0.0,
        "bat_p_charge": 0.0,
        "bat_p_discharge": 0.0,
        "bat_eff": 0.92,
        "bat_soc_init": 50.0,
        "bat_soc_min": 10.0,
        "bat_soc_max": 90.0,
        "bat_charge_strategy": "surplus_only",
        "th_enabled": False,
        "th_capacity": 0.0,
        "th_p_charge": 0.0,
        "th_p_discharge": 0.0,
        "th_loss": 0.0,
        "th_soc_init": 50.0,
        "th_soc_min": 10.0,
        "th_soc_max": 90.0,
        "th_eff_charge": 0.95,
        "th_eff_discharge": 0.95,
        "hp_enabled": False,
        "hp_capacity": 0.0,
        "hp_cop_mode": "fixed",
        "hp_cop_nominal": 3.5,
        "hp_min_frac": 0.0,
        "hp_site_cap": 0.0,
        "boiler_enabled": False,
        "boiler_capacity": 0.0,
        "boiler_eff": 0.92,
        "boiler_min_frac": 0.0,
        "boiler_fuel_type": "gas",
        "dh_enabled": False,
        "dh_capacity": 0.0,
        "dh_tariff": 0.0,
        "wkk_dispatch_mode": "electricity_led",
        "heat_dispatch_mode": "power_min_grid",
        "thermal_storage_strategy": "passive",
        "heat_source_priority_mode": "prefer_hp_then_storage_then_boiler_then_dh",
        "measurement_enabled": False,
        "measurement_time_resolution": "15min",
        "measurement_expected_resolution": "15min",
        "measurement_timezone": TZ,
        "measurement_power_unit_mode": "kW",
        "measurement_resample_policy": "mean_to_hourly",
        "measurement_gap_fill_method": "none",
        "measurement_comparison_mode": "grid_import",
        "evaluation_calibration_metrics_enabled": False,
        "evaluation_peak_p1": 0.95,
        "evaluation_peak_p2": 0.99,
        "evaluation_max_exceedance_duration_h": 0.0,
        "evaluation_max_exceedance_energy_kWh": 0.0,
        "evaluation_robust_green_margin_fraction": 0.05,
        "last_load_df": None,
        "last_total_df": None,
        "last_generation_df": None,
        "last_measurement_bundle": None,
        "last_measurement_metadata": None,
        "last_validation_result": None,
        "last_measurement_filename": None,
        "bld_enable": False,
        "bld_sched_enable": False,
        "bld_t_heat_occ": 20.0,
        "bld_t_heat_unocc": 16.0,
        "bld_t_cool_occ": 24.0,
        "bld_t_cool_unocc": 27.0,
        "bld_cop_winter": 3.6,
        "bld_cop_spring": 4.1,
        "bld_cop_summer": 4.4,
        "bld_cop_autumn": 4.0,
        "bld_eer_winter": 3.3,
        "bld_eer_spring": 3.5,
        "bld_eer_summer": 3.1,
        "bld_eer_autumn": 3.4,
        "bld_eta_wtw": 0.80,
        "bld_qv10": 0.40,
        "bld_g_value": 0.50,
        "bld_shading_factor": 0.80,
        "pe_enable": False,
        "pe_occ": 10.0,
        "pe_unocc": 3.0,
        "pr_enable": False,
        "pr_pp": 0.0,
        "pr_pi": 0.0,
        "mob_n_cars": 0,
        "mob_p_charger_max": 11.0,
        "mob_duty_cycle": 0.30,
        "mob_site_cap": 0.0,
        "ov_enable": False,
        "ov_occ": 2.0,
        "ov_unocc": 0.5,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


init_state()


@st.cache_data(show_spinner=False)
def load_weather(path: str) -> pd.DataFrame:
    return read_weather_excel(path, year=None, freq=None, tz=TZ)


WEATHER_DF = load_weather(str(WEATHER_PATH))
if not WEATHER_DF.index.is_unique:
    dupes = WEATHER_DF.index[WEATHER_DF.index.duplicated(keep=False)]
    st.error(f"Weather index bevat duplicates: {len(dupes)} rijen")
    st.stop()
st.caption(
    f"Kunstmatig weatherjaar geladen: {len(WEATHER_DF)} tijdstappen | "
    f"van {WEATHER_DF.index.min().strftime('%m-%d %H:%M')} "
    f"tot {WEATHER_DF.index.max().strftime('%m-%d %H:%M')} | "
    f"kolommen: {', '.join(WEATHER_DF.columns)}"
)
st.caption(f"Beschikbare weather columns: {', '.join(WEATHER_DF.columns)}")
DT_HOURS = (WEATHER_DF.index[1] - WEATHER_DF.index[0]).total_seconds() / 3600.0 if len(WEATHER_DF.index) > 1 else 1.0


def series_dt_hours(df: pd.DataFrame | None) -> float:
    if df is None or not isinstance(df.index, pd.DatetimeIndex) or len(df.index) < 2:
        return DT_HOURS
    return float((df.index[1] - df.index[0]).total_seconds() / 3600.0)


def safe_contract_value(raw_value) -> float | None:
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    return None if value <= 0 else value


def consultant_summary(df: pd.DataFrame, grid_cap_kW: float | None) -> dict[str, str]:
    grid_eval = df.attrs.get("grid_evaluation") or {}
    kpis = df.attrs.get("kpis") or {}
    peak_ratio = grid_eval.get("peak_ratio_to_contract")
    p99_ratio = grid_eval.get("p99_ratio_to_contract")
    stoplight = str(grid_eval.get("stoplight", "unknown")).capitalize()
    unserved_heat = float(kpis.get("annual_heat_unserved_kWhth", 0.0) or 0.0)
    annual_gas = float(kpis.get("annual_gas_input_kWh", 0.0) or 0.0)
    return {
        "Consultant summary": stoplight,
        "Peak netimport vs contract": "-" if peak_ratio is None else f"{float(peak_ratio):.2f}x",
        "P99 netimport vs contract": "-" if p99_ratio is None else f"{float(p99_ratio):.2f}x",
        "Exceedance duration": "-" if grid_eval.get("contract_exceedance_hours") is None else f"{float(grid_eval['contract_exceedance_hours']):.1f} h",
        "Peak netimport": f"{float(grid_eval.get('peak_grid_import_kW', 0.0) or 0.0):.1f} kW",
        "Grid contract": "-" if grid_cap_kW is None else f"{float(grid_cap_kW):.1f} kW",
        "Annual grid import": f"{float(kpis.get('annual_grid_import_kWh', 0.0) or 0.0):.0f} kWh",
        "Annual grid export": f"{float(kpis.get('annual_grid_export_kWh', 0.0) or 0.0):.0f} kWh",
        "Annual gas input": f"{annual_gas:.0f} kWh",
        "Annual unmet heat": f"{unserved_heat:.0f} kWhth",
    }


def current_shape_factor() -> float:
    mapped = float(SHAPE_FACTOR_BY_SHAPE[BuildingShape(st.session_state["def_shape"])])
    return float(st.session_state["def_shape_manual"]) if st.session_state["def_manual_shape"] else mapped


def schedule_editor(
    prefix: str,
    default_days=("Mon", "Tue", "Wed", "Thu", "Fri"),
    default_start=8,
    default_end=18,
) -> WeeklySchedule:
    days = st.multiselect("Days", DAY_LABELS, default=list(default_days), key=f"{prefix}_days")
    c1, c2 = st.columns(2)
    with c1:
        start = st.number_input("Start hour", 0, 23, int(default_start), 1, key=f"{prefix}_start")
    with c2:
        end = st.number_input("End hour", 1, 24, int(default_end), 1, key=f"{prefix}_end")
    return WeeklySchedule(
        days_active=tuple(DAY_TO_INT[d] for d in days) if days else (0, 1, 2, 3, 4),
        start_hour=int(start),
        end_hour=int(end),
    )


def subload_payload(list_key: str, mode: str):
    out = []
    for sl in st.session_state[list_key]:
        payload = {
            "name": sl["name"],
            "schedule": WeeklySchedule(
                days_active=tuple(DAY_TO_INT[d] for d in sl["days"]) if sl["days"] else (0, 1, 2, 3, 4),
                start_hour=int(sl["start"]),
                end_hour=int(sl["end"]),
            ),
        }
        if mode == "occ":
            payload["p_occ_W_per_m2"] = float(sl["p_occ"])
            payload["p_unocc_W_per_m2"] = float(sl["p_unocc"])
        else:
            payload["p_process_kW"] = float(sl["p_process"])
            payload["p_idle_kW"] = float(sl["p_idle"])
        out.append(payload)
    return out or None


def edit_occ_subloads(list_key: str, prefix: str, default_occ: float, default_unocc: float):
    if st.button("Add subload", key=f"{prefix}_add"):
        st.session_state[list_key].append({
            "name": f"{prefix.capitalize()} {len(st.session_state[list_key]) + 1}",
            "days": ("Mon", "Tue", "Wed", "Thu", "Fri"),
            "start": 8,
            "end": 18,
            "p_occ": default_occ,
            "p_unocc": default_unocc,
        })
    for i, sl in enumerate(list(st.session_state[list_key])):
        with st.expander(sl["name"], expanded=False):
            sl["name"] = st.text_input("Naam", value=sl["name"], key=f"{prefix}_name_{i}")
            if st.button("Verwijder", key=f"{prefix}_rm_{i}"):
                st.session_state[list_key].pop(i)
                st.rerun()
            sl["days"] = tuple(st.multiselect("Days", DAY_LABELS, default=list(sl["days"]), key=f"{prefix}_days_{i}"))
            c1, c2 = st.columns(2)
            with c1:
                sl["start"] = st.number_input("Start hour", 0, 23, int(sl["start"]), 1, key=f"{prefix}_start_{i}")
            with c2:
                sl["end"] = st.number_input("End hour", 1, 24, int(sl["end"]), 1, key=f"{prefix}_end_{i}")
            c3, c4 = st.columns(2)
            with c3:
                sl["p_occ"] = st.number_input("P_occ [W/m²]", value=float(sl["p_occ"]), step=0.2, key=f"{prefix}_pocc_{i}")
            with c4:
                sl["p_unocc"] = st.number_input("P_unocc [W/m²]", value=float(sl["p_unocc"]), step=0.2, key=f"{prefix}_punocc_{i}")
            st.session_state[list_key][i] = sl


def edit_process_subloads():
    if st.button("Add process", key="proc_add"):
        st.session_state["pprocess_subloads"].append({
            "name": f"Process {len(st.session_state['pprocess_subloads']) + 1}",
            "days": ("Mon", "Tue", "Wed", "Thu", "Fri"),
            "start": 9,
            "end": 17,
            "p_process": 10.0,
            "p_idle": 0.0,
        })
    for i, sl in enumerate(list(st.session_state["pprocess_subloads"])):
        with st.expander(sl["name"], expanded=False):
            sl["name"] = st.text_input("Naam", value=sl["name"], key=f"proc_name_{i}")
            if st.button("Verwijder", key=f"proc_rm_{i}"):
                st.session_state["pprocess_subloads"].pop(i)
                st.rerun()
            sl["days"] = tuple(st.multiselect("Days", DAY_LABELS, default=list(sl["days"]), key=f"proc_days_{i}"))
            c1, c2 = st.columns(2)
            with c1:
                sl["start"] = st.number_input("Start hour", 0, 23, int(sl["start"]), 1, key=f"proc_start_{i}")
            with c2:
                sl["end"] = st.number_input("End hour", 1, 24, int(sl["end"]), 1, key=f"proc_end_{i}")
            c3, c4 = st.columns(2)
            with c3:
                sl["p_process"] = st.number_input("P_process [kW]", value=float(sl["p_process"]), step=1.0, key=f"proc_pp_{i}")
            with c4:
                sl["p_idle"] = st.number_input("P_idle [kW]", value=float(sl["p_idle"]), step=1.0, key=f"proc_pi_{i}")
            st.session_state["pprocess_subloads"][i] = sl


def first_week(df: pd.DataFrame) -> pd.DataFrame:
    start = df.index.min()
    return df.loc[(df.index >= start) & (df.index < start + pd.Timedelta(days=7))]


def preview_week_chart(df: pd.DataFrame, cols: list[str], title: str):
    available = [c for c in cols if c in df.columns]
    if available:
        st.markdown(f"**{title}**")
        st.line_chart(first_week(df)[available])

def plot_peak_grid_import_week_stacked(
    df: pd.DataFrame,
    title: str = "Peak grid import week",
    contract_kW: float | None = None,
):
    if df is None or df.empty or "P_grid_import_kW" not in df.columns:
        return

    week_df = df.loc[find_peak_week(df, "P_grid_import_kW")].copy()
    week_df = week_df.reset_index().rename(columns={"index": "timestamp"})

    supply_cols = [
        "P_pv_kW",
        "P_wkk_el_kW",
        "P_battery_discharge_kW",
        "P_grid_import_kW",
    ]
    supply_cols = [c for c in supply_cols if c in week_df.columns]

    st.markdown(f"**{title}**")

    if not supply_cols:
        st.info("Geen assets beschikbaar voor stacked plot.")
        return

    supply_long = week_df[["timestamp"] + supply_cols].melt(
        id_vars="timestamp",
        var_name="asset",
        value_name="power_kW",
    )

    stacked_area = (
        alt.Chart(supply_long)
        .mark_area()
        .encode(
            x=alt.X("timestamp:T", title="Tijd"),
            y=alt.Y("power_kW:Q", stack=True, title="Vermogen [kW]"),
            color=alt.Color("asset:N", title="Assets"),
            tooltip=[
                "timestamp:T",
                "asset:N",
                alt.Tooltip("power_kW:Q", format=".2f"),
            ],
        )
    )

    layers = [stacked_area]

    if contract_kW is not None:
        contract_df = pd.DataFrame(
            {
                "timestamp": week_df["timestamp"],
                "contract_kW": float(contract_kW),
            }
        )

        contract_line = (
            alt.Chart(contract_df)
            .mark_line(color="red", strokeDash=[8, 4], strokeWidth=2)
            .encode(
                x=alt.X("timestamp:T", title="Tijd"),
                y=alt.Y("contract_kW:Q", title="Vermogen [kW]"),
                tooltip=[
                    "timestamp:T",
                    alt.Tooltip("contract_kW:Q", format=".2f", title="Contractvermogen"),
                ],
            )
        )

        layers.append(contract_line)

    chart = alt.layer(*layers).interactive()
    st.altair_chart(chart, use_container_width=True)

    if "battery_soc_pct" in week_df.columns:
        st.markdown("**Battery SoC [%]**")
        soc_chart = (
            alt.Chart(week_df)
            .mark_line(strokeWidth=2)
            .encode(
                x=alt.X("timestamp:T", title="Tijd"),
                y=alt.Y("battery_soc_pct:Q", title="Battery SoC [%]"),
                tooltip=["timestamp:T", alt.Tooltip("battery_soc_pct:Q", format=".2f")],
            )
            .interactive()
        )
        st.altair_chart(soc_chart, use_container_width=True)

def energy_kpis(df: pd.DataFrame) -> dict:
    zero = pd.Series(0.0, index=df.index)
    peak_before = float(df.get("P_grid_import_before_battery_kW", zero).max())
    peak_after = float(df.get("P_grid_import_kW", zero).max())
    peak_contract_excess = float(df.get("P_grid_contract_excess_kW", zero).max())
    out = {
        "Peak load [kW]": round(float(df["P_load_total_kW"].max()), 2) if "P_load_total_kW" in df else 0.0,
        "Peak grid import before battery [kW]": round(peak_before, 2),
        "Peak grid import after battery [kW]": round(peak_after, 2),
        "Peak shaving by battery [kW]": round(max(peak_before - peak_after, 0.0), 2),
        "Peak contract exceedance [kW]": round(peak_contract_excess, 2),
        "Annual electric load [kWh]": round(float((df.get("P_load_total_kW", zero) * DT_HOURS).sum()), 0),
        "Annual PV [kWh]": round(float((df.get("P_pv_kW", zero) * DT_HOURS).sum()), 0),
        "Annual WKK el [kWh]": round(float((df.get("P_wkk_el_kW", zero) * DT_HOURS).sum()), 0),
        "Annual HP el [kWh]": round(float((df.get("P_hp_el_kW", zero) * DT_HOURS).sum()), 0),
        "Annual grid import [kWh]": round(float((df.get("P_grid_import_kW", zero) * DT_HOURS).sum()), 0),
        "Annual grid export [kWh]": round(float((df.get("P_grid_export_kW", zero) * DT_HOURS).sum()), 0),
        "Annual battery charge [kWh]": round(float((df.get("P_battery_charge_kW", zero) * DT_HOURS).sum()), 0),
        "Annual battery discharge [kWh]": round(float((df.get("P_battery_discharge_kW", zero) * DT_HOURS).sum()), 0),
        "Annual heat demand [kWhth]": round(float((df.get("Q_heat_demand_kWth", zero) * DT_HOURS).sum()), 0),
        "Annual heat supplied [kWhth]": round(float((df.get("Q_heat_supply_total_kWth", zero) * DT_HOURS).sum()), 0),
        "Annual heat unmet [kWhth]": round(float((df.get("Q_heat_unserved_final_kWth", zero) * DT_HOURS).sum()), 0),
        "Annual boiler heat [kWhth]": round(float((df.get("Q_boiler_th_kWth", zero) * DT_HOURS).sum()), 0),
        "Annual district heat [kWhth]": round(float((df.get("Q_dh_th_kWth", zero) * DT_HOURS).sum()), 0),
        "Annual WKK heat used [kWhth]": round(float((df.get("Q_wkk_used_kWth", zero) * DT_HOURS).sum()), 0),
        "Annual WKK heat dumped [kWhth]": round(float((df.get("Q_wkk_dumped_kWth", zero) * DT_HOURS).sum()), 0),
        "Annual thermal storage discharge [kWhth]": round(float((df.get("Q_thermal_storage_discharge_kWth", zero) * DT_HOURS).sum()), 0),
    }
    return out

def compute_grid_stress_metrics(df: pd.DataFrame, contract_kW: float):
    if contract_kW is None or contract_kW <= 0:
        return {}

    imp = df.get("P_grid_import_kW")
    if imp is None:
        return {}

    dt_h = series_dt_hours(df)
    metrics = {}

    metrics["hours_above_90"] = float((imp > 0.9 * contract_kW).sum() * dt_h)
    metrics["hours_above_95"] = float((imp > 0.95 * contract_kW).sum() * dt_h)
    metrics["hours_above_100"] = float((imp > contract_kW).sum() * dt_h)
    metrics["avg_headroom_kW"] = float((contract_kW - imp).clip(lower=0).mean())

    peak = float(imp.max()) if len(imp) else 0.0
    avg = float(imp.mean()) if len(imp) else 0.0
    metrics["load_factor"] = avg / peak if peak > 0 else 0.0

    total_load = df.get("P_load_total_kW")
    if total_load is not None:
        total_energy = float((total_load * dt_h).sum())
        grid_energy = float((imp * dt_h).sum())
        metrics["self_sufficiency"] = 1.0 - (grid_energy / total_energy) if total_energy > 0 else 0.0
    else:
        metrics["self_sufficiency"] = None

    return metrics

def render_grid_stoplight(df: pd.DataFrame, grid_cap_kW: float | None, cfg=None) -> dict | None:
    if df is None or df.empty or "P_grid_import_kW" not in df.columns:
        st.info("Stoplicht beschikbaar zodra een total-run met netimport is uitgevoerd.")
        return None

    grid_eval = df.attrs.get("grid_evaluation")
    if grid_eval is None:
        if cfg is None:
            st.info("Stoplicht beschikbaar zodra evaluatieconfig of contractvermogen beschikbaar is.")
            return None
        grid_eval = evaluate_grid(
            df,
            grid_contract_kW=grid_cap_kW,
            stoplight_thresholds=getattr(cfg.evaluation, "stoplight_thresholds", None),
            max_exceedance_duration_h=float(getattr(cfg.evaluation, "max_exceedance_duration_h", 0.0)),
            max_exceedance_energy_kWh=float(getattr(cfg.evaluation, "max_exceedance_energy_kWh", 0.0)),
            peak_percentiles=tuple(getattr(cfg.evaluation, "peak_percentiles", (0.95, 0.99))),
            robust_green_margin_fraction=float(getattr(cfg.evaluation, "robust_green_margin_fraction", 0.05)),
        )
        df.attrs["grid_evaluation"] = grid_eval

    status = str(grid_eval.get("stoplight", "unknown"))
    contract = grid_eval.get("grid_contract_kW")
    peak = float(grid_eval.get("peak_grid_import_kW", 0.0) or 0.0)
    peak_ratio = grid_eval.get("peak_ratio_to_contract")
    exceed_h = grid_eval.get("contract_exceedance_hours")
    exceed_energy = grid_eval.get("contract_exceedance_energy_kWh")
    worst_run = grid_eval.get("worst_continuous_exceedance_h")
    p99 = grid_eval.get("p99_grid_import_kW")

    if status == "green":
        st.success(f"Groen · piek netimport {peak:.1f} kW bij contract {float(contract):.1f} kW")
    elif status == "orange":
        st.warning(f"Oranje · netimport zit dicht op of net boven contract ({peak:.1f} / {float(contract):.1f} kW)")
    elif status == "red":
        st.error(f"Rood · netimport overschrijdt contract ({peak:.1f} / {float(contract):.1f} kW)")
    else:
        st.info("Stoplicht onbekend: stel een contractvermogen > 0 in.")
        return grid_eval

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Peak import [kW]", f"{peak:.1f}")
    c2.metric("Peak / contract", "-" if peak_ratio is None else f"{float(peak_ratio):.2f}x")
    c3.metric("Exceedance duration [h]", "-" if exceed_h is None else f"{float(exceed_h):.2f}")
    c4.metric("Exceedance energy [kWh]", "-" if exceed_energy is None else f"{float(exceed_energy):.1f}")
    c5.metric("Worst continuous exceedance [h]", "-" if worst_run is None else f"{float(worst_run):.2f}")

    if p99 is not None:
        st.caption(f"P99 grid import: {float(p99):.1f} kW")

    return grid_eval


def render_grid_duration_curve(df: pd.DataFrame, grid_cap_kW: float | None) -> None:
    if df is None or df.empty or "P_grid_import_kW" not in df.columns:
        return

    duration_df = build_grid_duration_curve(df, contract_kW=grid_cap_kW)
    duration_long = duration_df[["duration_h", "P_grid_import_kW", "P_grid_contract_kW"]].melt(
        id_vars="duration_h",
        var_name="series",
        value_name="power_kW",
    )
    duration_long = duration_long.dropna(subset=["power_kW"])

    st.markdown("**Grid load duration curve**")
    chart = (
        alt.Chart(duration_long)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("duration_h:Q", title="Uren per jaar (gesorteerd)"),
            y=alt.Y("power_kW:Q", title="Vermogen [kW]"),
            color=alt.Color("series:N", title="Serie"),
            tooltip=[
                alt.Tooltip("duration_h:Q", format=".0f"),
                alt.Tooltip("power_kW:Q", format=".1f"),
                "series:N"
            ],
        )
        .interactive()
    )
    st.altair_chart(chart, use_container_width=True)


def render_measurement_metadata(metadata: dict | None) -> None:
    if not metadata:
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rijen", str(metadata.get("row_count", "-")))
    c2.metric("Duplicates", str(metadata.get("duplicate_timestamp_count", "-")))
    c3.metric("Detecteerde resolutie", str(metadata.get("detected_resolution") or "-")[:18])
    coverage = metadata.get("coverage_fraction_vs_expected")
    c4.metric("Coverage", "-" if coverage is None else f"{100.0 * float(coverage):.1f}%")

    st.caption(
        f"Bron: {metadata.get('source_path', '-') } · timezone: {metadata.get('timezone', '-') } · "
        f"expected_resolution: {metadata.get('expected_resolution', '-') } · resample_policy: {metadata.get('resample_policy', '-') }"
    )
    warnings = list(metadata.get("warnings", []))
    if warnings:
        for w in warnings:
            st.warning(w)


def render_validation_results(validation: dict | None) -> None:
    if not validation:
        return

    warnings = validation.get("warnings", [])
    for w in warnings:
        st.warning(w)

    metrics = validation.get("metrics", {})
    peak = validation.get("peak_summary", {})

    st.markdown("**Calibration metrics**")
    for label in ["hourly", "daily", "monthly"]:
        m = metrics.get(label, {})
        if not m:
            continue
        st.markdown(f"***{label.capitalize()}***")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("N", m.get("n_points", 0))
        c2.metric("RMSE", "-" if pd.isna(m.get("rmse")) else f"{float(m['rmse']):.2f}")
        c3.metric("MAE", "-" if pd.isna(m.get("mae")) else f"{float(m['mae']):.2f}")
        c4.metric("NMBE [%]", "-" if pd.isna(m.get("nmbe_pct")) else f"{float(m['nmbe_pct']):.2f}")
        c5.metric("CV(RMSE) [%]", "-" if pd.isna(m.get("cv_rmse_pct")) else f"{float(m['cv_rmse_pct']):.2f}")

    if peak:
        st.markdown("**Peak comparison**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Peak simulated [kW]", "-" if pd.isna(peak.get("peak_simulated")) else f"{float(peak['peak_simulated']):.2f}")
        c2.metric("Peak measured [kW]", "-" if pd.isna(peak.get("peak_measured")) else f"{float(peak['peak_measured']):.2f}")
        c3.metric("Peak bias [kW]", "-" if pd.isna(peak.get("peak_bias_kW")) else f"{float(peak['peak_bias_kW']):.2f}")
        c4.metric("Peak bias [%]", "-" if pd.isna(peak.get("peak_bias_pct")) else f"{float(peak['peak_bias_pct']):.2f}")

    aligned = validation.get("aligned")
    if aligned is not None and not aligned.empty:
        st.markdown("**Simulated vs measured**")
        compare_df = aligned[["simulated", "measured"]].reset_index()
        ts_col = compare_df.columns[0]
        compare_long = compare_df.melt(id_vars=ts_col, var_name="series", value_name="value")
        chart = (
            alt.Chart(compare_long)
            .mark_line()
            .encode(
                x=alt.X(f"{ts_col}:T", title="Tijd"),
                y=alt.Y("value:Q", title="Vermogen"),
                color=alt.Color("series:N", title="Serie"),
                tooltip=[f"{ts_col}:T", "series:N", alt.Tooltip("value:Q", format=".2f")],
            )
            .interactive()
        )
        st.altair_chart(chart, use_container_width=True)

        st.markdown("**Scatter simulated vs measured**")
        scatter_base = aligned.reset_index()[["measured", "simulated", "residual"]].copy()
        lo = float(min(scatter_base["measured"].min(), scatter_base["simulated"].min()))
        hi = float(max(scatter_base["measured"].max(), scatter_base["simulated"].max()))
        ref_df = pd.DataFrame({"ref_x": [lo, hi], "ref_y": [lo, hi]})
        scatter_chart = alt.layer(
            alt.Chart(scatter_base).mark_circle(size=45).encode(
                x=alt.X("measured:Q", title="Measured"),
                y=alt.Y("simulated:Q", title="Simulated"),
                tooltip=[alt.Tooltip("measured:Q", format=".2f"), alt.Tooltip("simulated:Q", format=".2f"), alt.Tooltip("residual:Q", format=".2f")],
            ),
            alt.Chart(ref_df).mark_line(strokeDash=[6, 4]).encode(x="ref_x:Q", y="ref_y:Q")
        ).interactive()
        st.altair_chart(scatter_chart, use_container_width=True)

        st.markdown("**Residual**")
        residual_chart = (
            alt.Chart(aligned.reset_index())
            .mark_line()
            .encode(
                x=alt.X(f"{aligned.reset_index().columns[0]}:T", title="Tijd"),
                y=alt.Y("residual:Q", title="Residual [sim - meas]"),
                tooltip=[alt.Tooltip("residual:Q", format=".2f")],
            )
            .interactive()
        )
        st.altair_chart(residual_chart, use_container_width=True)

    monthly = validation.get("aggregations", {}).get("monthly")
    if monthly is not None and not monthly.empty:
        st.markdown("**Monthly totals**")
        monthly_reset = monthly[["simulated", "measured"]].reset_index()
        ts_col = monthly_reset.columns[0]
        monthly_long = monthly_reset.melt(id_vars=ts_col, var_name="series", value_name="value")
        month_chart = (
            alt.Chart(monthly_long)
            .mark_bar()
            .encode(
                x=alt.X(f"{ts_col}:T", title="Maand"),
                y=alt.Y("value:Q", title="Totaal"),
                color=alt.Color("series:N", title="Serie"),
                xOffset="series:N",
                tooltip=[f"{ts_col}:T", "series:N", alt.Tooltip("value:Q", format=".2f")],
            )
            .interactive()
        )
        st.altair_chart(month_chart, use_container_width=True)



def render_sanity_checks(df: pd.DataFrame | None) -> None:
    if df is None:
        return
    checks = df.attrs.get("sanity_checks") or {}
    if not checks:
        return
    st.markdown("**Interne checks**")
    c1, c2, c3 = st.columns(3)
    c1.metric("Heat balance ok", "Ja" if checks.get("heat_balance_within_tolerance") else "Nee")
    c2.metric("Negatieve fysica", "Nee" if checks.get("no_non_physical_negatives") else "Ja")
    c3.metric("Capacity checks", "Ok" if checks.get("all_capacity_constraints_respected") else "Overschreden")
    st.caption(
        f"max |heat residual| = {float(checks.get('heat_balance_max_abs_residual_kWth', float('nan'))):.4f} kWth"
    )
    if checks.get("non_physical_negative_columns"):
        st.warning("Niet-fysische negatieve waarden in: " + ", ".join(checks["non_physical_negative_columns"]))
    violations = checks.get("capacity_violations") or {}
    active_violations = {k: v for k, v in violations.items() if float(v) > 1e-9}
    if active_violations:
        st.warning("Capacity violations: " + ", ".join(f"{k}={v:.3f}" for k, v in active_violations.items()))


def build_export_bundle(df: pd.DataFrame, measurement_metadata: dict | None = None, validation_result: dict | None = None) -> bytes:
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("energy_system_results.csv", df.to_csv())

        summary = {
            "kpis": df.attrs.get("kpis", {}),
            "grid_evaluation": df.attrs.get("grid_evaluation", {}),
            "sanity_checks": df.attrs.get("sanity_checks", {}),
            "measurement_metadata": measurement_metadata or {},
            "validation_metrics": (validation_result or {}).get("metrics", {}),
            "validation_peak_summary": (validation_result or {}).get("peak_summary", {}),
            "validation_warnings": (validation_result or {}).get("warnings", []),
        }
        zf.writestr("summary.json", json.dumps(summary, indent=2, default=str))

        if validation_result is not None and validation_result.get("aligned") is not None:
            zf.writestr("validation_aligned.csv", validation_result["aligned"].to_csv())
        if validation_result is not None:
            aggs = validation_result.get("aggregations", {})
            for name, agg_df in aggs.items():
                if agg_df is not None and not agg_df.empty:
                    zf.writestr(f"validation_{name}.csv", agg_df.to_csv())
    memory.seek(0)
    return memory.getvalue()



def get_building_overrides():
    if not st.session_state.get("bld_enable", False):
        return None

    out = {
        "t_heat_set_occ_C": float(st.session_state["bld_t_heat_occ"]),
        "t_heat_set_unocc_C": float(st.session_state["bld_t_heat_unocc"]),
        "t_cool_set_occ_C": float(st.session_state["bld_t_cool_occ"]),
        "t_cool_set_unocc_C": float(st.session_state["bld_t_cool_unocc"]),
        "seasonal_cop_heat_by_season": {
            "winter": float(st.session_state["bld_cop_winter"]),
            "spring": float(st.session_state["bld_cop_spring"]),
            "summer": float(st.session_state["bld_cop_summer"]),
            "autumn": float(st.session_state["bld_cop_autumn"]),
        },
        "seasonal_eer_cool_by_season": {
            "winter": float(st.session_state["bld_eer_winter"]),
            "spring": float(st.session_state["bld_eer_spring"]),
            "summer": float(st.session_state["bld_eer_summer"]),
            "autumn": float(st.session_state["bld_eer_autumn"]),
        },
        "eta_wtw": float(st.session_state["bld_eta_wtw"]),
        "qv10_m3ph_per_m2": float(st.session_state["bld_qv10"]),
        "g_value": float(st.session_state["bld_g_value"]),
        "shading_factor": float(st.session_state["bld_shading_factor"]),
    }

    if st.session_state.get("bld_sched_enable", False):
        out["occupancy_schedule"] = WeeklySchedule(
            days_active=tuple(DAY_TO_INT[d] for d in st.session_state.get("bld_sched_days", ["Mon", "Tue", "Wed", "Thu", "Fri"])),
            start_hour=int(st.session_state.get("bld_sched_start", 8)),
            end_hour=int(st.session_state.get("bld_sched_end", 18)),
        )

    return out


def get_pelektro_overrides():
    if not st.session_state.get("pe_enable", False):
        return None
    return {
        "p_occ_W_per_m2": float(st.session_state["pe_occ"]),
        "p_unocc_W_per_m2": float(st.session_state["pe_unocc"]),
    }


def get_pprocess_overrides():
    if not st.session_state.get("pr_enable", False):
        return None
    return {
        "p_process_kW": float(st.session_state["pr_pp"]),
        "p_idle_kW": float(st.session_state["pr_pi"]),
    }


def get_pmobility_overrides():
    cap = float(st.session_state["mob_site_cap"])
    return {
        "n_cars": int(st.session_state["mob_n_cars"]),
        "p_charger_max_kW": float(st.session_state["mob_p_charger_max"]),
        "duty_cycle": float(st.session_state["mob_duty_cycle"]),
        "p_site_cap_kW": None if cap <= 0 else cap,
    }


def get_poverig_overrides():
    if not st.session_state.get("ov_enable", False):
        return None
    return {
        "p_occ_W_per_m2": float(st.session_state["ov_occ"]),
        "p_unocc_W_per_m2": float(st.session_state["ov_unocc"]),
    }


def build_cfg():
    pv_site_cap = None if float(st.session_state["pv_site_cap"]) <= 0 else float(st.session_state["pv_site_cap"])
    return make_default_load_config(
        building_type=BuildingType(st.session_state["def_building_type"]),
        year_class=YearClass(st.session_state["def_year_class"]),
        orientation=Orientation8(st.session_state["def_orientation"]),
        bvo_m2=float(st.session_state["def_bvo"]),
        floors=int(st.session_state["def_floors"]),
        window_to_wall_ratio=float(st.session_state["def_wwr"]),
        shape_factor=current_shape_factor(),
        building_overrides=get_building_overrides(),
        pelektro_overrides=get_pelektro_overrides(),
        pprocess_overrides=get_pprocess_overrides(),
        pmobility_overrides=get_pmobility_overrides(),
        poverig_overrides=get_poverig_overrides(),
        pv_overrides={
            "enabled": bool(st.session_state["pv_enabled"]),
            "installed_capacity_kWp": float(st.session_state["pv_cap"]),
            "tilt_deg": float(st.session_state["pv_tilt"]),
            "azimuth_deg": float(st.session_state["pv_azimuth"]),
            "performance_ratio": float(st.session_state["pv_pr"]),
            "inverter_efficiency": float(st.session_state["pv_inv_eff"]),
            "temp_coeff_per_C": float(st.session_state["pv_temp_coeff"]),
            "site_cap_kW": pv_site_cap,
        },
        wkk_overrides={
            "enabled": bool(st.session_state["wkk_enabled"]),
            "p_rated_el_kW": float(st.session_state["wkk_p_rated"]),
            "min_load_fraction": float(st.session_state["wkk_min_frac"]),
            "electrical_efficiency": float(st.session_state["wkk_el_eff"]),
            "thermal_efficiency": float(st.session_state["wkk_th_eff"]),
            "dispatch_mode": str(st.session_state["wkk_dispatch_mode"]),
        },
        battery_overrides={
            "enabled": bool(st.session_state["bat_enabled"]),
            "capacity_kWh": float(st.session_state["bat_capacity"]),
            "p_charge_max_kW": float(st.session_state["bat_p_charge"]),
            "p_discharge_max_kW": float(st.session_state["bat_p_discharge"]),
            "efficiency_roundtrip": float(st.session_state["bat_eff"]),
            "soc_init_fraction": float(st.session_state["bat_soc_init"]) / 100.0,
            "soc_min_fraction": float(st.session_state["bat_soc_min"]) / 100.0,
            "soc_max_fraction": float(st.session_state["bat_soc_max"]) / 100.0,
            "dispatch_mode": "self_consumption",
            "charge_strategy": str(st.session_state["bat_charge_strategy"]),
        },
        heat_pump_overrides={
            "enabled": bool(st.session_state["hp_enabled"]),
            "capacity_kWth": float(st.session_state["hp_capacity"]),
            "cop_mode": str(st.session_state["hp_cop_mode"]),
            "cop_nominal": float(st.session_state["hp_cop_nominal"]),
            "min_part_load_fraction": float(st.session_state["hp_min_frac"]),
            "site_cap_electric_kW": None if float(st.session_state["hp_site_cap"]) <= 0 else float(st.session_state["hp_site_cap"]),
        },
        boiler_overrides={
            "enabled": bool(st.session_state["boiler_enabled"]),
            "capacity_kWth": float(st.session_state["boiler_capacity"]),
            "thermal_efficiency": float(st.session_state["boiler_eff"]),
            "min_part_load_fraction": float(st.session_state["boiler_min_frac"]),
            "fuel_type": str(st.session_state["boiler_fuel_type"]),
        },
        district_heat_overrides={
            "enabled": bool(st.session_state["dh_enabled"]),
            "capacity_kWth": float(st.session_state["dh_capacity"]),
            "tariff_placeholder": float(st.session_state["dh_tariff"]),
        },
        heat_system_overrides={
            "heating_dispatch_mode": str(st.session_state["heat_dispatch_mode"]),
            "wkk_dispatch_mode": str(st.session_state["wkk_dispatch_mode"]),
            "thermal_storage_strategy": str(st.session_state["thermal_storage_strategy"]),
            "source_priority_mode": str(st.session_state["heat_source_priority_mode"]),
            "shared_grid_contract_cap": True,
        },
        measurement_overrides={
            "enabled": bool(st.session_state["measurement_enabled"]),
            "time_resolution": str(st.session_state["measurement_time_resolution"]),
            "expected_resolution": str(st.session_state["measurement_expected_resolution"]),
            "timezone": str(st.session_state["measurement_timezone"]),
            "power_unit_mode": str(st.session_state["measurement_power_unit_mode"]),
            "resample_policy": str(st.session_state["measurement_resample_policy"]),
            "gap_fill_method": str(st.session_state["measurement_gap_fill_method"]),
            "comparison_mode": str(st.session_state["measurement_comparison_mode"]),
        },
        evaluation_overrides={
            "grid_contract_kW": float(st.session_state["grid_cap_kW"]),
            "peak_percentiles": (
                float(st.session_state["evaluation_peak_p1"]),
                float(st.session_state["evaluation_peak_p2"]),
            ),
            "calibration_metrics_enabled": bool(st.session_state["evaluation_calibration_metrics_enabled"]),
            "max_exceedance_duration_h": float(st.session_state["evaluation_max_exceedance_duration_h"]),
            "max_exceedance_energy_kWh": float(st.session_state["evaluation_max_exceedance_energy_kWh"]),
            "robust_green_margin_fraction": float(st.session_state["evaluation_robust_green_margin_fraction"]),
        },
        thermal_storage_overrides={
            "enabled": bool(st.session_state["th_enabled"]),
            "capacity_kWh_th": float(st.session_state["th_capacity"]),
            "p_charge_max_kW": float(st.session_state["th_p_charge"]),
            "p_discharge_max_kW": float(st.session_state["th_p_discharge"]),
            "loss_factor_per_hour": float(st.session_state["th_loss"]),
            "soc_init_fraction": float(st.session_state["th_soc_init"]) / 100.0,
            "soc_min_fraction": float(st.session_state["th_soc_min"]) / 100.0,
            "soc_max_fraction": float(st.session_state["th_soc_max"]) / 100.0,
            "efficiency_charge": float(st.session_state["th_eff_charge"]),
            "efficiency_discharge": float(st.session_state["th_eff_discharge"]),
        },
    )


st.info(
    f"Weerbron: {WEATHER_PATH.name} · periode {WEATHER_DF.index.min().year}–{WEATHER_DF.index.max().year} · resolutie {SIM_FREQ}."
)

load_tab, generation_tab, heat_tab, storage_tab, total_tab, validation_tab = st.tabs(["Load", "Generation", "Heat", "Storage", "Total", "Validation"])


with load_tab:
    t_def, t_bld, t_pe, t_pr, t_mob, t_ov, t_run = st.tabs([
        "Defaults voor load",
        "gebouwmodel",
        "p_elektro",
        "Processen",
        "Mobiliteit",
        "overig",
        "Run en results voor alleen load",
    ])

    with t_def:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.selectbox("Gebouwtype", [x.value for x in BuildingType], key="def_building_type")
        with c2:
            st.selectbox("Bouwjaar-klasse", [x.value for x in YearClass], key="def_year_class")
        with c3:
            st.selectbox("Orientatie", [x.value for x in Orientation8], key="def_orientation")
        with c4:
            st.number_input("BVO [m²]", min_value=50.0, step=50.0, key="def_bvo")

        c5, c6, c7, c8 = st.columns(4)
        with c5:
            st.number_input("Floors", min_value=1, step=1, key="def_floors")
        with c6:
            st.slider("Window-to-wall ratio", 0.05, 0.80, key="def_wwr")
        with c7:
            st.selectbox("Building shape", [x.value for x in BuildingShape], key="def_shape")
        with c8:
            st.metric("Mapped shape factor", f"{float(SHAPE_FACTOR_BY_SHAPE[BuildingShape(st.session_state['def_shape'])]):.2f}")

        st.checkbox("Manual override shape factor", key="def_manual_shape")
        if st.session_state["def_manual_shape"]:
            st.slider("Shape factor", 0.6, 2.0, step=0.05, key="def_shape_manual")

        cfg0 = build_cfg()
        st.write({
            "Default p_elektro P_occ [W/m²]": round(float(cfg0.pelektro.p_occ_W_per_m2), 2),
            "Default p_elektro P_unocc [W/m²]": round(float(cfg0.pelektro.p_unocc_W_per_m2), 2),
        })

    with t_bld:
        st.checkbox("Enable overrides", key="bld_enable")
        if st.session_state["bld_enable"]:
            st.checkbox("Override occupancy schedule", key="bld_sched_enable")
            if st.session_state["bld_sched_enable"]:
                schedule_editor("bld_sched")

            st.subheader("Setpoints")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.number_input("t_heat_set OCC [°C]", value=20.0, step=0.5, key="bld_t_heat_occ")
            with c2:
                st.number_input("t_heat_set UNOCC [°C]", value=16.0, step=0.5, key="bld_t_heat_unocc")
            with c3:
                st.number_input("t_cool_set OCC [°C]", value=24.0, step=0.5, key="bld_t_cool_occ")
            with c4:
                st.number_input("t_cool_set UNOCC [°C]", value=27.0, step=0.5, key="bld_t_cool_unocc")

            st.subheader("Seasonal COP / EER")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.number_input("COP winter", value=3.6, step=0.1, key="bld_cop_winter")
            with c2:
                st.number_input("COP spring", value=4.1, step=0.1, key="bld_cop_spring")
            with c3:
                st.number_input("COP summer", value=4.4, step=0.1, key="bld_cop_summer")
            with c4:
                st.number_input("COP autumn", value=4.0, step=0.1, key="bld_cop_autumn")

            c5, c6, c7, c8 = st.columns(4)
            with c5:
                st.number_input("EER winter", value=3.3, step=0.1, key="bld_eer_winter")
            with c6:
                st.number_input("EER spring", value=3.5, step=0.1, key="bld_eer_spring")
            with c7:
                st.number_input("EER summer", value=3.1, step=0.1, key="bld_eer_summer")
            with c8:
                st.number_input("EER autumn", value=3.4, step=0.1, key="bld_eer_autumn")

            st.subheader("HVAC / gebouw")
            c9, c10, c11, c12 = st.columns(4)
            with c9:
                st.slider("WTW [-]", 0.0, 0.95, 0.80, 0.01, key="bld_eta_wtw")
            with c10:
                st.number_input("qv10 [m³/h per m²]", value=0.40, step=0.1, key="bld_qv10")
            with c11:
                st.number_input("g-value [-]", value=0.50, step=0.01, key="bld_g_value")
            with c12:
                st.number_input("Shading factor [-]", value=0.80, step=0.01, key="bld_shading_factor")

        cfg = build_cfg()
        prev_df, _, _, _ = run_load_simulation(cfg, weather=WEATHER_DF.iloc[:24 * 7])
        preview_week_chart(prev_df, ["P_heat_kW", "P_cool_kW"], "Preview gebouwmodel")

    with t_pe:
        st.checkbox("Enable default override", key="pe_enable")
        if st.session_state["pe_enable"]:
            st.number_input("Default P_occ [W/m²]", value=10.0, step=0.5, key="pe_occ")
            st.number_input("Default P_unocc [W/m²]", value=3.0, step=0.5, key="pe_unocc")
        edit_occ_subloads("pelektro_subloads", "pe", 5.0, 1.0)

        pe_cfg = build_cfg()
        pe_df, _, _, _ = run_load_simulation(
            pe_cfg,
            weather=WEATHER_DF.iloc[:24 * 7],
            pelektro_subloads=subload_payload("pelektro_subloads", "occ"),
        )
        preview_week_chart(pe_df, ["P_elektro_kW"], "Preview p_elektro")

    with t_pr:
        st.checkbox("Enable single-block override", key="pr_enable")
        if st.session_state["pr_enable"]:
            st.number_input("Default P_process [kW]", value=0.0, step=1.0, key="pr_pp")
            st.number_input("Default P_idle [kW]", value=0.0, step=1.0, key="pr_pi")
        edit_process_subloads()

        pr_cfg = build_cfg()
        pr_df, _, _, _ = run_load_simulation(
            pr_cfg,
            weather=WEATHER_DF.iloc[:24 * 7],
            pprocess_subloads=subload_payload("pprocess_subloads", "process"),
        )
        preview_week_chart(pr_df, ["P_process_kW"], "Preview processen")

    with t_mob:
        st.number_input("Aantal auto's", min_value=0, value=0, step=1, key="mob_n_cars")
        st.number_input("Charger max [kW/car]", min_value=1.0, value=11.0, step=1.0, key="mob_p_charger_max")
        st.slider("Simultaneous charging fraction", 0.0, 1.0, 0.30, 0.05, key="mob_duty_cycle")
        st.number_input("Mobility site cap [kW] (0 = none)", min_value=0.0, value=0.0, step=5.0, key="mob_site_cap")

        mob_cfg = build_cfg()
        mob_df, _, _, _ = run_load_simulation(
            mob_cfg,
            weather=WEATHER_DF.iloc[:24 * 7],
        )
        preview_week_chart(mob_df, ["P_mobility_kW"], "Preview mobiliteit")

    with t_ov:
        st.checkbox("Enable default override", key="ov_enable")
        if st.session_state["ov_enable"]:
            st.number_input("Default P_occ [W/m²]", value=2.0, step=0.2, key="ov_occ")
            st.number_input("Default P_unocc [W/m²]", value=0.5, step=0.2, key="ov_unocc")
        edit_occ_subloads("poverig_subloads", "ov", 1.0, 0.2)

        ov_cfg = build_cfg()
        ov_df, _, _, _ = run_load_simulation(
            ov_cfg,
            weather=WEATHER_DF.iloc[:24 * 7],
            poverig_subloads=subload_payload("poverig_subloads", "occ"),
        )
        preview_week_chart(ov_df, ["P_overig_kW"], "Preview overig")

    with t_run:
        if st.button("Run load", type="primary"):
            cfg = build_cfg()
            df, fig_heat, fig_cool, _ = run_load_simulation(
                cfg,
                weather=WEATHER_DF,
                grid_cap_kW=None,
                pelektro_subloads=subload_payload("pelektro_subloads", "occ"),
                pprocess_subloads=subload_payload("pprocess_subloads", "process"),
                poverig_subloads=subload_payload("poverig_subloads", "occ"),
            )
            st.session_state["last_load_df"] = df
            st.write(energy_kpis(df))
            st.pyplot(fig_heat, clear_figure=True)
            st.pyplot(fig_cool, clear_figure=True)
            st.dataframe(df.head(200))

        if st.session_state["last_load_df"] is not None:
            preview_week_chart(st.session_state["last_load_df"], ["P_load_total_kW", "P_heat_kW", "P_cool_kW"], "Laatste load-run")


with generation_tab:
    g_pv, g_wkk, g_grid, g_run = st.tabs(["PV", "WKK", "Grid", "run en results voor generation"])

    with g_pv:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.checkbox("PV enabled", key="pv_enabled")
        with c2:
            st.number_input("Installed capacity [kWp]", min_value=0.0, step=10.0, key="pv_cap")
        with c3:
            st.number_input("Tilt [deg]", min_value=0.0, max_value=90.0, step=1.0, key="pv_tilt")
        with c4:
            st.number_input("Azimuth [deg]", min_value=0.0, max_value=360.0, step=5.0, key="pv_azimuth")

        c5, c6, c7, c8 = st.columns(4)
        with c5:
            st.number_input("Performance ratio", min_value=0.0, max_value=1.2, step=0.01, key="pv_pr")
        with c6:
            st.number_input("Inverter efficiency", min_value=0.0, max_value=1.0, step=0.01, key="pv_inv_eff")
        with c7:
            st.number_input("Temp coeff [/°C]", step=0.001, key="pv_temp_coeff")
        with c8:
            st.number_input("Site cap [kW] (0 = none)", min_value=0.0, step=10.0, key="pv_site_cap")

        cfg = build_cfg()
        pv_df = simulate_pv(WEATHER_DF.index, cfg.pv, WEATHER_DF)
        preview_week_chart(pv_df, ["P_pv_kW"], "Preview PV")
        st.write({
            "PV enabled": bool(cfg.pv.enabled),
            "Installed capacity [kWp]": float(cfg.pv.installed_capacity_kWp),
            "Max GHI [W/m²]": float(WEATHER_DF["ghi_Wm2"].max()) if "ghi_Wm2" in WEATHER_DF.columns else None,
            "Peak PV [kW]": round(float(pv_df["P_pv_kW"].max()), 2),
            "Annual PV [kWh]": round(float((pv_df["P_pv_kW"] * DT_HOURS).sum()), 0),
        })

    with g_wkk:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.checkbox("WKK enabled", key="wkk_enabled")
        with c2:
            st.number_input("Rated electrical power [kW]", min_value=0.0, step=10.0, key="wkk_p_rated")
        with c3:
            st.slider("Min load fraction", 0.0, 1.0, 0.0, 0.05, key="wkk_min_frac")

        c4, c5, c6 = st.columns(3)
        with c4:
            st.number_input("Electrical efficiency", min_value=0.01, max_value=1.0, step=0.01, key="wkk_el_eff")
        with c5:
            st.number_input("Thermal efficiency", min_value=0.0, max_value=1.0, step=0.01, key="wkk_th_eff")
        with c6:
            st.selectbox(
                "Dispatch mode",
                [
                    "electricity_led",
                    "thermal_led",
                    "heat_led",
                    "hybrid_peak_shaving",
                    "heat_led_with_electric_cap",
                    "must_run",
                    "off",
                ],
                key="wkk_dispatch_mode",
            )

        cfg = build_cfg()
        demand_df = pd.DataFrame(
            {"P_residual_before_wkk_kW": float(st.session_state["wkk_p_rated"]) * 0.7, "Q_heat_demand_kWth": float(st.session_state["wkk_p_rated"]) * 0.5},
            index=WEATHER_DF.index,
        )
        wkk_df = dispatch_wkk(WEATHER_DF.index, cfg.wkk, demand_df)
        preview_week_chart(wkk_df, ["P_wkk_el_kW", "P_wkk_th_kW", "Q_wkk_used_kWth"], "Preview WKK")
        st.write({
            "Peak WKK el [kW]": round(float(wkk_df["P_wkk_el_kW"].max()), 2),
            "Peak WKK th [kWth]": round(float(wkk_df["P_wkk_th_kW"].max()), 2),
            "Annual WKK fuel input [kWh]": round(float((wkk_df["F_wkk_fuel_kWh_per_h"] * DT_HOURS).sum()), 0),
            "Annual WKK useful heat [kWhth]": round(float((wkk_df["Q_wkk_used_kWth"] * DT_HOURS).sum()), 0),
        })

    with g_grid:
        st.number_input("Grid contract power [kW]", min_value=0.0, step=5.0, key="grid_cap_kW")
        st.caption("0 = geen expliciete begrenzing in de simulatie.")
        st.write({
            "Configured grid contract power [kW]": float(st.session_state["grid_cap_kW"])
        })

    with g_run:
        cfg = build_cfg()
        gen_df, _, _, _ = run_energy_system_simulation(
            cfg,
            weather=WEATHER_DF,
            grid_cap_kW=(None if float(st.session_state["grid_cap_kW"]) == 0 else float(st.session_state["grid_cap_kW"])),
            pelektro_subloads=subload_payload("pelektro_subloads", "occ"),
            pprocess_subloads=subload_payload("pprocess_subloads", "process"),
            poverig_subloads=subload_payload("poverig_subloads", "occ"),
        )
        st.session_state["last_generation_df"] = gen_df

        cols = [c for c in ["P_pv_kW", "P_wkk_el_kW", "P_generation_total_kW", "P_battery_charge_kW", "P_battery_discharge_kW", "P_grid_import_kW"] if c in gen_df.columns]
        if cols:
            st.line_chart(first_week(gen_df)[cols])

        st.write({
            "Peak PV [kW]": round(float(gen_df["P_pv_kW"].max()), 2) if "P_pv_kW" in gen_df else 0.0,
            "Peak WKK [kW]": round(float(gen_df["P_wkk_el_kW"].max()), 2) if "P_wkk_el_kW" in gen_df else 0.0,
            "Peak total generation [kW]": round(float(gen_df["P_generation_total_kW"].max()), 2) if "P_generation_total_kW" in gen_df else 0.0,
            "Annual PV [kWh]": round(float((gen_df["P_pv_kW"] * DT_HOURS).sum()), 0) if "P_pv_kW" in gen_df else 0.0,
            "Annual WKK [kWh]": round(float((gen_df["P_wkk_el_kW"] * DT_HOURS).sum()), 0) if "P_wkk_el_kW" in gen_df else 0.0,
        })


with heat_tab:
    h_hp, h_boiler, h_dh = st.tabs(["Heat pump", "Boiler", "District heat"])

    with h_hp:
        st.checkbox("Heat pump enabled", key="hp_enabled")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.number_input("Capacity [kWth]", min_value=0.0, step=10.0, key="hp_capacity")
        with c2:
            st.selectbox("COP mode", ["fixed", "seasonal", "weather_dependent"], key="hp_cop_mode")
        with c3:
            st.number_input("Nominal COP", min_value=0.1, step=0.1, key="hp_cop_nominal")
        c4, c5 = st.columns(2)
        with c4:
            st.slider("Min part load fraction", 0.0, 1.0, 0.0, 0.05, key="hp_min_frac")
        with c5:
            st.number_input("Electric site cap [kW] (0 = none)", min_value=0.0, step=5.0, key="hp_site_cap")

    with h_boiler:
        st.checkbox("Boiler enabled", key="boiler_enabled")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.number_input("Capacity [kWth]", min_value=0.0, step=10.0, key="boiler_capacity")
        with c2:
            st.number_input("Thermal efficiency", min_value=0.01, max_value=1.0, step=0.01, key="boiler_eff")
        with c3:
            st.slider("Min part load fraction", 0.0, 1.0, 0.0, 0.05, key="boiler_min_frac")
        with c4:
            st.selectbox("Fuel type", ["gas", "biogas", "hydrogen", "generic"], key="boiler_fuel_type")

    with h_dh:
        st.checkbox("District heat enabled", key="dh_enabled")
        c1, c2 = st.columns(2)
        with c1:
            st.number_input("Capacity [kWth]", min_value=0.0, step=10.0, key="dh_capacity")
        with c2:
            st.number_input("Tariff placeholder", min_value=0.0, step=0.01, key="dh_tariff")


with storage_tab:
    s_bat, s_heat = st.tabs(["Batterijen", "Warmte opslag"])

    with s_bat:
        st.checkbox("Battery enabled", key="bat_enabled")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.number_input("Capacity [kWh]", min_value=0.0, step=10.0, key="bat_capacity")
            st.number_input("Initial SoC [%]", min_value=0.0, max_value=100.0, step=5.0, key="bat_soc_init")
        with c2:
            st.number_input("Charge power [kW]", min_value=0.0, step=10.0, key="bat_p_charge")
            st.number_input("Minimum SoC [%]", min_value=0.0, max_value=100.0, step=5.0, key="bat_soc_min")
        with c3:
            st.number_input("Discharge power [kW]", min_value=0.0, step=10.0, key="bat_p_discharge")
            st.number_input("Maximum SoC [%]", min_value=0.0, max_value=100.0, step=5.0, key="bat_soc_max")
        st.number_input("Roundtrip efficiency", min_value=0.0, max_value=1.0, step=0.01, key="bat_eff")
        st.selectbox(
            "Charge strategy",
            options=["surplus_only", "grid_headroom"],
            format_func=lambda x: {
                "surplus_only": "Alleen laden met lokaal overschot (PV/WKK)",
                "grid_headroom": "Laden vanuit net tot contractvermogen",
            }[x],
            key="bat_charge_strategy",
        )
        st.caption("Actieve dispatch: self-consumption. De batterij laadt bij overschot en ontlaadt bij resterende netvraag.")

    with s_heat:
        st.checkbox("Thermal storage enabled", key="th_enabled")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.number_input("Capacity [kWh_th]", min_value=0.0, step=10.0, key="th_capacity")
            st.number_input("Initial SoC [%]", min_value=0.0, max_value=100.0, step=5.0, key="th_soc_init")
        with c2:
            st.number_input("Charge power [kWth]", min_value=0.0, step=10.0, key="th_p_charge")
            st.number_input("Minimum SoC [%]", min_value=0.0, max_value=100.0, step=5.0, key="th_soc_min")
        with c3:
            st.number_input("Discharge power [kWth]", min_value=0.0, step=10.0, key="th_p_discharge")
            st.number_input("Maximum SoC [%]", min_value=0.0, max_value=100.0, step=5.0, key="th_soc_max")
        c4, c5, c6 = st.columns(3)
        with c4:
            st.number_input("Loss factor per hour", min_value=0.0, max_value=1.0, step=0.01, key="th_loss")
        with c5:
            st.number_input("Charge efficiency", min_value=0.01, max_value=1.0, step=0.01, key="th_eff_charge")
        with c6:
            st.number_input("Discharge efficiency", min_value=0.01, max_value=1.0, step=0.01, key="th_eff_discharge")
        st.caption("Thermische opslag is nu onderdeel van de warmteketen in de totale simulatie.")


with total_tab:
    st.write("Hier run je de totale simulatie en zie je vooral het resterende vermogen uit het net.")

    if st.button("Run total", type="primary"):
        try:
            cfg = build_cfg()
            df, fig_heat, fig_balance, _ = run_energy_system_simulation(
                cfg,
                weather=WEATHER_DF,
                grid_cap_kW=safe_contract_value(st.session_state.get("grid_cap_kW")),
                pelektro_subloads=subload_payload("pelektro_subloads", "occ"),
                pprocess_subloads=subload_payload("pprocess_subloads", "process"),
                poverig_subloads=subload_payload("poverig_subloads", "occ"),
            )
            st.session_state["last_total_df"] = df
            contract = safe_contract_value(st.session_state.get("grid_cap_kW"))
            render_grid_stoplight(df, contract, cfg=cfg)
            kpis = energy_kpis(df)
            c1, c2 = st.columns(2)
            with c1:
                st.write({k: v for k, v in kpis.items() if "heat" not in k.lower() and "boiler" not in k.lower() and "district" not in k.lower()})
            with c2:
                st.write({k: v for k, v in kpis.items() if "heat" in k.lower() or "boiler" in k.lower() or "district" in k.lower()})

            render_sanity_checks(df)
            st.markdown("### Consultant summary")
            st.json(consultant_summary(df, contract))
            st.markdown("### Grid stress indicatoren")

            m = compute_grid_stress_metrics(df, contract)

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Hours > 90%", f"{m.get('hours_above_90', 0):.1f} h")
            c2.metric("Hours > 95%", f"{m.get('hours_above_95', 0):.1f} h")
            c3.metric("Hours > 100%", f"{m.get('hours_above_100', 0):.1f} h")
            c4.metric("Avg headroom", f"{m.get('avg_headroom_kW', 0):.1f} kW")
            c5.metric("Load factor", f"{m.get('load_factor', 0):.2f}")

            if m.get("self_sufficiency") is not None:
                st.caption(f"Self-sufficiency: {m['self_sufficiency']*100:.1f}%")



            st.markdown("### Worst grid week (netbelasting)")

            if "P_grid_import_kW" in df.columns:
                weekly_peak = df["P_grid_import_kW"].rolling(168).max()
                idx = weekly_peak.idxmax()
                week = df.loc[idx - pd.Timedelta(hours=168): idx].copy()

                week = week.reset_index().rename(columns={"index": "timestamp"})

                base = alt.Chart(week).mark_line().encode(
                    x="timestamp:T",
                    y=alt.Y("P_grid_import_kW:Q", title="Netimport [kW]"),
                    tooltip=["timestamp:T", alt.Tooltip("P_grid_import_kW:Q", format=".1f")]
                )

                layers = [base]

                if contract is not None:
                    contract_line = alt.Chart(pd.DataFrame({"y": [contract]})).mark_rule(
                        color="red",
                        strokeDash=[6, 4]
                    ).encode(y="y")
                    layers.append(contract_line)

                st.altair_chart(alt.layer(*layers).interactive(), use_container_width=True)
            plot_peak_grid_import_week_stacked(
                df,
                "Peak grid import week – stacked assets",
                contract_kW=safe_contract_value(st.session_state.get("grid_cap_kW")),
            )

            worst_week_idx = find_worst_grid_week(df)
            worst_week_cols = [c for c in ["P_grid_import_kW", "P_grid_contract_excess_kW", "P_grid_export_kW"] if c in df.columns]
            if len(worst_week_idx) > 0 and worst_week_cols:
                st.markdown("**Worst grid week – diagnostics**")
                st.line_chart(df.loc[worst_week_idx, worst_week_cols])

            render_grid_duration_curve(
                df,
                safe_contract_value(st.session_state.get("grid_cap_kW")),
            )

            st.pyplot(fig_heat, clear_figure=True)
            st.pyplot(fig_balance, clear_figure=True)
            heat_cols = [c for c in ["Q_heat_demand_kWth", "Q_hp_th_kWth", "Q_wkk_used_kWth", "Q_boiler_th_kWth", "Q_dh_th_kWth", "Q_thermal_storage_discharge_kWth", "Q_heat_unserved_final_kWth"] if c in df.columns]
            if heat_cols:
                st.markdown("**Heat balance – first week**")
                st.line_chart(first_week(df)[heat_cols])
            st.dataframe(df.head(200))
            export_zip = build_export_bundle(
                df,
                measurement_metadata=st.session_state.get("last_measurement_metadata"),
                validation_result=st.session_state.get("last_validation_result"),
            )
            c_export1, c_export2 = st.columns(2)
            with c_export1:
                st.download_button(
                    "Download CSV",
                    df.to_csv().encode("utf-8"),
                    file_name="energy_system_results.csv",
                    mime="text/csv",
                )
            with c_export2:
                st.download_button(
                    "Download export bundle (.zip)",
                    export_zip,
                    file_name="energy_system_export_bundle.zip",
                    mime="application/zip",
                )
        except Exception as exc:
            st.error(f"Total-run mislukt: {exc}")

    if st.session_state["last_total_df"] is not None:
        render_grid_stoplight(
            st.session_state["last_total_df"],
            safe_contract_value(st.session_state.get("grid_cap_kW")),
        )
        render_sanity_checks(st.session_state["last_total_df"])
        plot_peak_grid_import_week_stacked(
            st.session_state["last_total_df"],
            "Laatste total-run – peak grid import week",
            contract_kW=float(st.session_state["grid_cap_kW"]) if st.session_state.get("grid_cap_kW") is not None else None,
        )
        if "battery_soc_pct" in st.session_state["last_total_df"].columns:
            st.markdown("**Battery SoC [%]**")
            st.line_chart(first_week(st.session_state["last_total_df"])[["battery_soc_pct"]])

with validation_tab:
    st.write("Upload meetdata en vergelijk die met de laatste total-run.")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.checkbox("Meetdata ingeschakeld", key="measurement_enabled")
        st.selectbox("Power unit mode", ["kW", "kWh_per_interval"], key="measurement_power_unit_mode")
    with c2:
        st.selectbox("Expected resolution", ["15min", "30min", "1h"], key="measurement_expected_resolution")
        st.selectbox("Gap fill", ["none", "ffill", "bfill", "interpolate_time", "zero"], key="measurement_gap_fill_method")
    with c3:
        st.selectbox("Comparison mode", ["grid_import", "grid_export", "electric_load", "gas", "heat"], key="measurement_comparison_mode")
        st.selectbox("Resample policy", ["mean_to_hourly", "sum_to_hourly", "mean", "sum", "none"], key="measurement_resample_policy")

    uploaded = st.file_uploader("Upload meetdata (.csv, .xlsx)", type=["csv", "txt", "xlsx", "xls"], key="measurement_upload")

    if uploaded is not None:
        suffix = Path(uploaded.name).suffix or ".csv"
        tmp_path = APP_DIR / f"_tmp_measurements{suffix}"
        tmp_path.write_bytes(uploaded.getbuffer())
        st.session_state["last_measurement_filename"] = uploaded.name

        if st.button("Verwerk meetdata", key="process_measurements"):
            try:
                bundle, metadata = load_measurement_bundle(
                    tmp_path,
                    timezone=str(st.session_state["measurement_timezone"]),
                    expected_resolution=str(st.session_state["measurement_expected_resolution"]),
                    power_unit_mode=str(st.session_state["measurement_power_unit_mode"]),
                    gap_fill_method=str(st.session_state["measurement_gap_fill_method"]),
                    hourly_resample_policy=str(st.session_state["measurement_resample_policy"]),
                )
                st.session_state["last_measurement_bundle"] = bundle
                st.session_state["last_measurement_metadata"] = metadata
                st.session_state["last_validation_result"] = None
            except Exception as exc:
                st.error(f"Meetdata kon niet worden verwerkt: {exc}")

    if st.session_state.get("last_measurement_filename"):
        st.caption(f"Laatste meetbestand: {st.session_state['last_measurement_filename']}")

    render_measurement_metadata(st.session_state.get("last_measurement_metadata"))

    measurement_bundle = st.session_state.get("last_measurement_bundle")
    if measurement_bundle is not None:
        st.markdown("**Preview measured_15m**")
        preview_cols = [c for c in ["P_grid_import_kW", "P_grid_export_kW", "P_electric_load_kW", "F_gas_kW", "Q_heat_kWth"] if c in measurement_bundle["measured_15m"].columns]
        if preview_cols:
            st.line_chart(first_week(measurement_bundle["measured_15m"])[preview_cols])
        st.dataframe(measurement_bundle["measured_15m"].head(100))

    if st.session_state.get("last_total_df") is None:
        st.info("Run eerst de total-simulatie om validatie te kunnen doen.")
    elif measurement_bundle is None:
        st.info("Upload en verwerk eerst meetdata.")
    else:
        if st.button("Vergelijk simulatie met meetdata", type="primary", key="run_validation"):
            try:
                validation = prepare_validation_dataset(
                    st.session_state["last_total_df"],
                    measurement_bundle,
                    comparison_mode=str(st.session_state["measurement_comparison_mode"]),
                    resample_policy=str(st.session_state["measurement_resample_policy"]),
                )
                st.session_state["last_validation_result"] = validation
            except Exception as exc:
                st.error(f"Validatie mislukt: {exc}")

    render_validation_results(st.session_state.get("last_validation_result"))

    if st.session_state.get("last_validation_result") is not None:
        aligned = st.session_state["last_validation_result"].get("aligned")
        if aligned is not None and not aligned.empty:
            st.download_button(
                "Download validation CSV",
                aligned.to_csv().encode("utf-8"),
                file_name="validation_aligned_timeseries.csv",
                mime="text/csv",
            )
