"""
src.load package

This package contains the building electricity demand ("load") simulation engine.

Design principles:
- Each sub-model exposes a small, predictable interface, typically:
    simulate(index: pd.DatetimeIndex, params: <Dataclass>) -> pd.Series  (kW)
- Defaults are provided via profiles/registry, and can be overridden by the user.
- total.py orchestrates running all sub-models and summing them.

Public API (stable for the GUI/app):
- run_load_simulation(...) -> pd.DataFrame with component series + total
- make_default_load_config(...) -> LoadConfig (defaults + overrides merged)
"""

from __future__ import annotations

from .profiles import (
    # Enums
    BuildingType,
    YearClass,
    Orientation8,
    Season,
    BuildingShape,
    # Schedule + helpers
    WeeklySchedule,
    SHAPE_FACTOR_BY_SHAPE,
    # Config / profiles
    BuildingArchetype,
    LoadConfig,
    PVConfig,
    WKKConfig,
    BatteryConfig,
    ThermalStorageConfig,
    make_default_load_config,
)

from .total import (
    run_load_simulation,
    run_energy_system_simulation,
)

__all__ = [
    # Enums / types
    "BuildingType",
    "YearClass",
    "Orientation8",
    "Season",
    "BuildingShape",
    # Schedule + helpers
    "WeeklySchedule",
    "SHAPE_FACTOR_BY_SHAPE",
    # Config / profiles
    "BuildingArchetype",
    "LoadConfig",
    "PVConfig",
    "WKKConfig",
    "BatteryConfig",
    "ThermalStorageConfig",
    "make_default_load_config",
    # Orchestration
    "run_load_simulation",
    "run_energy_system_simulation",
]