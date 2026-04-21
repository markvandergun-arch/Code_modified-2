from __future__ import annotations

import numpy as np
import pandas as pd


_ALLOWED_FUEL_TYPES = {"gas", "biogas", "hydrogen", "generic"}


def dispatch_boiler(index: pd.DatetimeIndex, config, demand_df: pd.DataFrame) -> pd.DataFrame:
    """
    Dispatch a boiler against remaining explicit thermal demand.

    Expected optional demand columns:
      - Q_heat_unserved_after_hp_kWth
      - Q_heat_unserved_kWth
      - Q_heat_demand_kWth
      - Q_heat_kWth

    Returned columns:
      - Q_boiler_th_kWth
      - Q_boiler_unserved_after_boiler_kWth
      - F_boiler_fuel_kW
      - F_boiler_fuel_kWh_per_h
      - F_boiler_gas_kW
      - F_boiler_gas_kWh_per_h
      - boiler_status
      - boiler_load_fraction
      - boiler_fuel_type
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a pandas.DatetimeIndex")
    if not isinstance(demand_df, pd.DataFrame):
        raise TypeError("demand_df must be a pandas.DataFrame")
    if len(index) != len(demand_df.index):
        raise ValueError("index and demand_df must have the same length")

    enabled = bool(getattr(config, "enabled", False))
    q_capacity = float(getattr(config, "capacity_kWth", 0.0))
    eta = float(getattr(config, "thermal_efficiency", 0.92))
    min_frac = float(getattr(config, "min_part_load_fraction", 0.0))
    fuel_type = str(getattr(config, "fuel_type", "gas") or "gas").strip().lower()

    if q_capacity < 0:
        raise ValueError("config.capacity_kWth must be >= 0")
    if not (0.0 < eta <= 1.0):
        raise ValueError("config.thermal_efficiency must be between 0 and 1")
    if not (0.0 <= min_frac <= 1.0):
        raise ValueError("config.min_part_load_fraction must be between 0 and 1")
    if fuel_type not in _ALLOWED_FUEL_TYPES:
        raise ValueError(f"Unsupported boiler fuel_type='{fuel_type}'. Allowed: {sorted(_ALLOWED_FUEL_TYPES)}")

    heat_demand = _get_heat_demand(demand_df)
    zeros = np.zeros(len(index), dtype=float)

    if (not enabled) or q_capacity <= 0:
        return pd.DataFrame(
            {
                "Q_boiler_th_kWth": zeros,
                "Q_boiler_unserved_after_boiler_kWth": heat_demand,
                "F_boiler_fuel_kW": zeros,
                "F_boiler_fuel_kWh_per_h": zeros,
                "F_boiler_gas_kW": zeros,
                "F_boiler_gas_kWh_per_h": zeros,
                "boiler_status": zeros.astype(int),
                "boiler_load_fraction": zeros,
                "boiler_fuel_type": np.full(len(index), fuel_type, dtype=object),
            },
            index=index,
        )

    q_target = np.minimum(np.clip(heat_demand, 0.0, None), q_capacity)

    if min_frac > 0:
        q_min = q_capacity * min_frac
        q_target = np.where(q_target >= q_min, q_target, 0.0)

    fuel = q_target / eta
    q_unserved = np.clip(heat_demand - q_target, 0.0, None)
    status = (q_target > 0).astype(int)
    load_fraction = np.where(q_capacity > 0, q_target / q_capacity, 0.0)

    # keep generic fuel bookkeeping and explicit gas aliases for compatibility
    if fuel_type == "gas":
        gas_input = fuel.copy()
    else:
        gas_input = zeros.copy()

    return pd.DataFrame(
        {
            "Q_boiler_th_kWth": q_target.astype(float),
            "Q_boiler_unserved_after_boiler_kWth": q_unserved.astype(float),
            "F_boiler_fuel_kW": fuel.astype(float),
            "F_boiler_fuel_kWh_per_h": fuel.astype(float),
            "F_boiler_gas_kW": gas_input.astype(float),
            "F_boiler_gas_kWh_per_h": gas_input.astype(float),
            "boiler_status": status.astype(int),
            "boiler_load_fraction": load_fraction.astype(float),
            "boiler_fuel_type": np.full(len(index), fuel_type, dtype=object),
        },
        index=index,
    )


def _get_heat_demand(demand_df: pd.DataFrame) -> np.ndarray:
    for col in [
        "Q_heat_unserved_after_hp_kWth",
        "Q_heat_unserved_kWth",
        "Q_heat_demand_kWth",
        "Q_heat_kWth",
    ]:
        if col in demand_df.columns:
            return np.clip(demand_df[col].to_numpy(dtype=float), 0.0, None)
    return np.zeros(len(demand_df.index), dtype=float)
