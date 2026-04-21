# src/load/pelektro.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from .profiles import SimpleOccLoadDefaults, WeeklySchedule


# =============================================================================
# Optional: subload model (v1)
# =============================================================================

@dataclass(frozen=True)
class ElectricSubLoad:
    """
    Optional sub-load for p_elektro.

    All powers are in W/m² (floor area based) to keep it consistent with the defaults.
    The total p_elektro is the sum of all subloads.
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


# =============================================================================
# Public API
# =============================================================================

def simulate(
    index: pd.DatetimeIndex,
    defaults: SimpleOccLoadDefaults,
    *,
    bvo_m2: float,
    subloads: Optional[List[ElectricSubLoad]] = None,
    name: str = "P_elektro_kW",
) -> pd.Series:
    """
    Simulate p_elektro as an occupancy-based electric load.

    Two modes:
    1) Simple mode (no subloads):
        P(t) = (p_occ_W_per_m2 or p_unocc_W_per_m2) * BVO
    2) Subload mode:
        P(t) = sum_k [ (p_occ_k or p_unocc_k) * BVO ] with each subload's own schedule

    Parameters
    ----------
    index:
        Simulation time index (e.g., 15-min typical year).
    defaults:
        SimpleOccLoadDefaults with p_occ_W_per_m2, p_unocc_W_per_m2 and a schedule.
    bvo_m2:
        Gross floor area.
    subloads:
        Optional list of ElectricSubLoad for finer modelling.
    name:
        Series name for output.

    Returns
    -------
    pd.Series in kW, aligned to index.
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a pandas.DatetimeIndex")
    if bvo_m2 <= 0:
        raise ValueError("bvo_m2 must be > 0")

    if subloads is None or len(subloads) == 0:
        # Simple occupancy-based load
        occ = _schedule_mask(index, defaults.schedule)
        p_W_m2 = np.where(occ, float(defaults.p_occ_W_per_m2), float(defaults.p_unocc_W_per_m2))
        p_kW = (p_W_m2 * float(bvo_m2)) / 1000.0
        return pd.Series(p_kW, index=index, name=name)

    # Subload mode
    total_kW = np.zeros(len(index), dtype=float)

    for sl in subloads:
    # support both dataclass-style and dict-style subloads
        name = sl.get("name", "subload") if isinstance(sl, dict) else getattr(sl, "name", "subload")
        schedule = sl["schedule"] if isinstance(sl, dict) else sl.schedule
        p_occ = sl["p_occ_W_per_m2"] if isinstance(sl, dict) else sl.p_occ_W_per_m2
        p_unocc = sl["p_unocc_W_per_m2"] if isinstance(sl, dict) else sl.p_unocc_W_per_m2

        if p_occ < 0 or p_unocc < 0:
            raise ValueError(f"Electric subload '{name}' has negative intensity; not allowed.")

        on = _schedule_mask(index, schedule)
        p_W_per_m2 = np.where(on, float(p_occ), float(p_unocc))
        total_kW += (p_W_per_m2 * float(bvo_m2)) / 1000.0

    return pd.Series(total_kW, index=index, name=name)