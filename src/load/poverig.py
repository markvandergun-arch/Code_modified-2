# src/load/poverig.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from .profiles import SimpleOccLoadDefaults, WeeklySchedule

# Optional: if you already added OtherSubLoad to profiles.py (as in our plan),
# we import it. Otherwise we define it locally to keep the module robust.
try:
    from .profiles import OtherSubLoad  # type: ignore
except Exception:  # pragma: no cover

    @dataclass(frozen=True)
    class OtherSubLoad:
        """
        One "other" (overig) load with its own schedule and two intensities (occupied/unoccupied).
        Intensity is per m2 floor area.
        """
        name: str
        p_occ_W_per_m2: float
        p_unocc_W_per_m2: float
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
    defaults: SimpleOccLoadDefaults,
    bvo_m2: float,
    *,
    subloads: Optional[List[OtherSubLoad]] = None,
    name: str = "P_overig_kW",
) -> pd.Series:
    """
    Simulate "overig" electric load.

    Two modes
    ---------
    1) Simple mode (no subloads):
        P(t) = p_occ_W_per_m2 during defaults.schedule
               p_unocc_W_per_m2 outside
        then multiplied by bvo_m2 and converted to kW.

    2) Subload mode (multiple named loads):
        P(t) = sum_k P_k(t)
        where each subload has its own schedule and (p_occ_W_per_m2, p_unocc_W_per_m2)

    Notes
    -----
    - This model is intentionally simple and uses only schedule gating + 2 intensity levels.
    - If subloads are provided, 'defaults' is ignored except for backward compatibility.
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a pandas.DatetimeIndex")
    if bvo_m2 <= 0:
        raise ValueError("bvo_m2 must be > 0")

    # ----------------------------
    # Mode 1: legacy/simple
    # ----------------------------
    if subloads is None or len(subloads) == 0:
        if defaults.p_occ_W_per_m2 < 0 or defaults.p_unocc_W_per_m2 < 0:
            raise ValueError("p_occ_W_per_m2 and p_unocc_W_per_m2 must be >= 0")

        on = _schedule_mask(index, defaults.schedule)
        p_W_per_m2 = np.where(on, float(defaults.p_occ_W_per_m2), float(defaults.p_unocc_W_per_m2))
        p_kW = (p_W_per_m2 * float(bvo_m2)) / 1000.0
        return pd.Series(p_kW, index=index, name=name)

    # ----------------------------
    # Mode 2: subloads
    # ----------------------------
    total_kW = np.zeros(len(index), dtype=float)

    for sl in subloads:
        if sl.p_occ_W_per_m2 < 0 or sl.p_unocc_W_per_m2 < 0:
            raise ValueError(f"Other subload '{sl.name}' has negative intensity; not allowed.")

        on = _schedule_mask(index, sl.schedule)
        p_W_per_m2 = np.where(on, float(sl.p_occ_W_per_m2), float(sl.p_unocc_W_per_m2))
        total_kW += (p_W_per_m2 * float(bvo_m2)) / 1000.0

    return pd.Series(total_kW, index=index, name=name)