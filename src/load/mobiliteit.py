# src/load/pmobiliteit.py
from __future__ import annotations

import numpy as np
import pandas as pd

from .profiles import MobilityLoadDefaults, WeeklySchedule


def _schedule_mask(index: pd.DatetimeIndex, schedule: WeeklySchedule) -> np.ndarray:
    schedule.validate()
    dow = index.dayofweek.to_numpy()
    hour = index.hour.to_numpy()
    is_day = np.isin(dow, np.array(list(schedule.days_active), dtype=int))
    is_hour = (hour >= int(schedule.start_hour)) & (hour < int(schedule.end_hour))
    return is_day & is_hour


def simulate(
    index: pd.DatetimeIndex,
    defaults: MobilityLoadDefaults,
    *,
    name: str = "P_mobility_kW",
) -> pd.Series:
    """
    Simple EV charging window model.

    Within charging_schedule:
      P = min(n_cars * p_charger_max_kW * duty_cycle, p_site_cap_kW if set)

    Outside window:
      P = 0

    Notes:
    - This is a "power block" model (no energy/SoC bookkeeping).
    - Smart charging / energy constraints can be added later in dispatch layer.
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a pandas.DatetimeIndex")

    if defaults.n_cars < 0:
        raise ValueError("n_cars must be >= 0")
    if defaults.p_charger_max_kW <= 0:
        raise ValueError("p_charger_max_kW must be > 0")
    if not (0.0 <= defaults.duty_cycle <= 1.0):
        raise ValueError("duty_cycle must be between 0 and 1")
    if defaults.p_site_cap_kW is not None and defaults.p_site_cap_kW <= 0:
        raise ValueError("p_site_cap_kW must be > 0 if provided")

    window = _schedule_mask(index, defaults.charging_schedule)

    p_raw = float(defaults.n_cars) * float(defaults.p_charger_max_kW) * float(defaults.duty_cycle)
    if defaults.p_site_cap_kW is not None:
        p_raw = min(p_raw, float(defaults.p_site_cap_kW))

    p = np.where(window, p_raw, 0.0)
    return pd.Series(p, index=index, name=name)