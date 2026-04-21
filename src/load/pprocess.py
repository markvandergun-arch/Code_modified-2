# src/load/pprocess.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from .profiles import ProcessLoadDefaults, WeeklySchedule

# Optional: if you already added ProcessSubLoad to profiles.py (as in our plan),
# we import it. Otherwise we define it locally to keep the module robust.
try:
    from .profiles import ProcessSubLoad  # type: ignore
except Exception:  # pragma: no cover

    @dataclass(frozen=True)
    class ProcessSubLoad:
        """
        One process with its own weekly schedule and two power levels.
        """
        name: str
        p_process_kW: float
        p_idle_kW: float
        schedule: WeeklySchedule


def _schedule_mask(index: pd.DatetimeIndex, schedule: WeeklySchedule) -> np.ndarray:
    schedule.validate()
    dow = index.dayofweek.to_numpy()
    hour = index.hour.to_numpy()
    is_day = np.isin(dow, np.array(list(schedule.days_active), dtype=int))
    is_hour = (hour >= int(schedule.start_hour)) & (hour < int(schedule.end_hour))
    return is_day & is_hour


def simulate(
    index: pd.DatetimeIndex,
    defaults: ProcessLoadDefaults,
    *,
    subloads: Optional[List[ProcessSubLoad]] = None,
    name: str = "P_process_kW",
) -> pd.Series:
    """
    Simulate process load.

    Two modes
    ---------
    1) Simple mode (no subloads):
        P(t) = p_process_kW during defaults.process_schedule
               p_idle_kW outside

    2) Subload mode (multiple named processes):
        P(t) = sum_k P_k(t)
        where each process k has its own schedule and (p_process_kW, p_idle_kW)

    Notes
    -----
    - This model is intentionally not dependent on building type/year (v1 design).
    - If subloads are provided, 'defaults' is ignored except for backward compatibility.
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a pandas.DatetimeIndex")

    # ----------------------------
    # Mode 1: legacy/simple
    # ----------------------------
    if subloads is None or len(subloads) == 0:
        if defaults.p_process_kW < 0 or defaults.p_idle_kW < 0:
            raise ValueError("p_process_kW and p_idle_kW must be >= 0")

        on = _schedule_mask(index, defaults.process_schedule)
        p = np.where(on, float(defaults.p_process_kW), float(defaults.p_idle_kW))
        return pd.Series(p, index=index, name=name)

    # ----------------------------
    # Mode 2: subloads
    # ----------------------------
    total_kW = np.zeros(len(index), dtype=float)

    for sl in subloads:
        if sl.p_process_kW < 0 or sl.p_idle_kW < 0:
            raise ValueError(f"Process '{sl.name}' has negative power; not allowed.")

        on = _schedule_mask(index, sl.schedule)
        p_k = np.where(on, float(sl.p_process_kW), float(sl.p_idle_kW))
        total_kW += p_k

    return pd.Series(total_kW, index=index, name=name)