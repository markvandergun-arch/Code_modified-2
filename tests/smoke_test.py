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
from src.load.total import run_energy_system_simulation, run_load_simulation
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

    print("Smoke test OK")


if __name__ == "__main__":
    main()
