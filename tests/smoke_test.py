from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "energieplanner-matplotlib"))
os.environ.setdefault("MPLBACKEND", "Agg")

from src.load.profiles import BuildingType, Orientation8, YearClass, make_default_load_config
from src.generation.pv import simulate_pv
from src.load.total import find_peak_week, run_energy_system_simulation, run_load_simulation
from src.load.weather import read_weather_excel


def main() -> None:
    weather_path = ROOT / "Weatherdata 2008-2021.xlsx"
    weather = read_weather_excel(weather_path).iloc[: 24 * 4]

    cfg = make_default_load_config(
        building_type=BuildingType.OFFICE,
        year_class=YearClass.Y2006_2014,
        orientation=Orientation8.S,
        bvo_m2=1000.0,
        heat_system_overrides={
            "reference_heating_enabled": True,
            "reference_cop_heat_by_season": {"winter": 3.5, "spring": 4.0, "summer": 4.2, "autumn": 3.8},
            "reference_eer_cool_by_season": {"winter": 3.3, "spring": 3.5, "summer": 3.1, "autumn": 3.4},
        },
    )

    load_df, *_ = run_load_simulation(cfg, weather=weather)
    total_df, *_ = run_energy_system_simulation(cfg, weather=weather, grid_cap_kW=500.0)

    required_load_cols = {"Q_heat_kWth", "Q_cool_kWth", "P_heat_ref_el_kW", "P_cool_el_kW"}
    required_total_cols = {"P_grid_import_kW", "P_load_total_kW", "Q_heat_supply_total_kWth"}
    missing = (required_load_cols - set(load_df.columns)) | (required_total_cols - set(total_df.columns))
    if missing:
        raise AssertionError(f"Smoke test mist resultaatkolommen: {sorted(missing)}")

    checks = total_df.attrs.get("sanity_checks", {})
    if checks and not checks.get("heat_balance_within_tolerance", True):
        raise AssertionError(f"Warmtebalans buiten tolerantie: {checks}")

    pv_cfg = make_default_load_config(
        building_type=BuildingType.OFFICE,
        year_class=YearClass.Y2006_2014,
        orientation=Orientation8.S,
        bvo_m2=1000.0,
        pv_overrides={
            "enabled": True,
            "installed_capacity_kWp": 100.0,
            "orientation_mode": "east_west",
            "east_west_split": 0.5,
        },
    ).pv
    pv_df = simulate_pv(weather.index, pv_cfg, weather)
    if not (pv_df["P_pv_kW"].round(9) == (pv_df["P_pv_east_kW"] + pv_df["P_pv_west_kW"]).round(9)).all():
        raise AssertionError("Oost-West PV telt niet op tot totaal PV.")

    no_export_weather = read_weather_excel(weather_path).iloc[24 * 160 : 24 * 164]
    no_export_cfg = make_default_load_config(
        building_type=BuildingType.OFFICE,
        year_class=YearClass.Y2006_2014,
        orientation=Orientation8.S,
        bvo_m2=100.0,
        pv_overrides={
            "enabled": True,
            "installed_capacity_kWp": 500.0,
            "export_mode": "no_export",
        },
        battery_overrides={
            "enabled": True,
            "capacity_kWh": 100.0,
            "p_charge_max_kW": 50.0,
            "p_discharge_max_kW": 0.0,
            "soc_init_fraction": 0.10,
            "soc_min_fraction": 0.10,
            "soc_max_fraction": 0.90,
        },
    )
    no_export_df, *_ = run_energy_system_simulation(no_export_cfg, weather=no_export_weather, grid_cap_kW=500.0)
    if float(no_export_df["P_grid_export_kW"].max()) > 1e-9:
        raise AssertionError("No-export scenario levert toch terug.")
    if float(no_export_df["P_battery_charge_kW"].sum()) <= 0.0:
        raise AssertionError("Batterij laadt niet op PV-overschot voor curtailment.")
    if float(no_export_df["P_pv_curtailed_kW"].sum()) <= 0.0:
        raise AssertionError("No-export scenario topt geen PV af.")

    idx = pd.date_range("2024-01-01", periods=24 * 14, freq="h", tz="Europe/Amsterdam")
    peak_df = pd.DataFrame({"P_grid_import_kW": 0.0}, index=idx)
    peak_df.loc[idx[24 * 7 + 12], "P_grid_import_kW"] = 100.0
    peak_week = find_peak_week(peak_df, "P_grid_import_kW")
    peak_pos = peak_week.get_loc(idx[24 * 7 + 12])
    if idx[24 * 7 + 12] not in peak_week or abs(peak_pos - len(peak_week) // 2) > 1:
        raise AssertionError("Piekweek is niet gecentreerd rond de piek.")

    print("Smoke test OK")


if __name__ == "__main__":
    main()
