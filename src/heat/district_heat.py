from __future__ import annotations

import numpy as np
import pandas as pd


def dispatch_district_heat(index: pd.DatetimeIndex, config, demand_df: pd.DataFrame) -> pd.DataFrame:
    """
    Dispatch district heat against remaining explicit thermal demand.

    Expected optional demand columns:
      - Q_heat_unserved_after_boiler_kWth
      - Q_heat_unserved_after_hp_kWth
      - Q_heat_unserved_kWth
      - Q_heat_demand_kWth
      - Q_heat_kWth

    Returned columns:
      - Q_dh_th_kWth
      - Q_heat_unserved_after_dh_kWth
      - district_heat_status
      - district_heat_load_fraction
      - district_heat_tariff_placeholder
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a pandas.DatetimeIndex")
    if not isinstance(demand_df, pd.DataFrame):
        raise TypeError("demand_df must be a pandas.DataFrame")
    if len(index) != len(demand_df.index):
        raise ValueError("index and demand_df must have the same length")

    enabled = bool(getattr(config, "enabled", False))
    q_capacity = float(getattr(config, "capacity_kWth", 0.0))
    tariff_placeholder = float(getattr(config, "tariff_placeholder", 0.0))

    if q_capacity < 0:
        raise ValueError("config.capacity_kWth must be >= 0")
    if tariff_placeholder < 0:
        raise ValueError("config.tariff_placeholder must be >= 0")

    heat_demand = _get_heat_demand(demand_df)
    zeros = np.zeros(len(index), dtype=float)

    if (not enabled) or q_capacity <= 0:
        return pd.DataFrame(
            {
                "Q_dh_th_kWth": zeros,
                "Q_heat_unserved_after_dh_kWth": heat_demand,
                "district_heat_status": zeros.astype(int),
                "district_heat_load_fraction": zeros,
                "district_heat_tariff_placeholder": np.full(len(index), tariff_placeholder, dtype=float),
            },
            index=index,
        )

    q_delivered = np.minimum(np.clip(heat_demand, 0.0, None), q_capacity)
    q_unserved = np.clip(heat_demand - q_delivered, 0.0, None)
    status = (q_delivered > 0).astype(int)
    load_fraction = np.where(q_capacity > 0, q_delivered / q_capacity, 0.0)

    return pd.DataFrame(
        {
            "Q_dh_th_kWth": q_delivered.astype(float),
            "Q_heat_unserved_after_dh_kWth": q_unserved.astype(float),
            "district_heat_status": status.astype(int),
            "district_heat_load_fraction": load_fraction.astype(float),
            "district_heat_tariff_placeholder": np.full(len(index), tariff_placeholder, dtype=float),
        },
        index=index,
    )


def _get_heat_demand(demand_df: pd.DataFrame) -> np.ndarray:
    for col in [
        "Q_heat_unserved_after_boiler_kWth",
        "Q_heat_unserved_after_hp_kWth",
        "Q_heat_unserved_kWth",
        "Q_heat_demand_kWth",
        "Q_heat_kWth",
    ]:
        if col in demand_df.columns:
            return np.clip(demand_df[col].to_numpy(dtype=float), 0.0, None)
    return np.zeros(len(demand_df.index), dtype=float)
