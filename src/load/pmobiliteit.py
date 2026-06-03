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


def _step_hours(index: pd.DatetimeIndex) -> np.ndarray:
    if len(index) < 2:
        return np.ones(len(index), dtype=float)
    diffs = np.diff(index.view("int64")) / 3_600_000_000_000.0
    fallback = float(np.nanmedian(diffs)) if len(diffs) else 1.0
    fallback = fallback if np.isfinite(fallback) and fallback > 0 else 1.0
    return np.append(diffs, fallback).astype(float)


def simulate(
    index: pd.DatetimeIndex,
    defaults: MobilityLoadDefaults,
    *,
    base_load_kW: pd.Series | None = None,
    grid_cap_kW: float | None = None,
    name: str = "P_mobility_kW",
) -> pd.Series:
    """
    Deterministic EV charging model.

    Direct charging starts at arrival and charges until the daily energy need is met.
    Smart charging distributes the daily energy need over available contract headroom.
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
    if defaults.battery_capacity_kWh < 0:
        raise ValueError("battery_capacity_kWh must be >= 0")
    if not (0.0 <= defaults.arrival_soc_pct <= 100.0):
        raise ValueError("arrival_soc_pct must be between 0 and 100")
    if not (0.0 <= defaults.target_departure_soc_pct <= 100.0):
        raise ValueError("target_departure_soc_pct must be between 0 and 100")
    if not (0.0 <= defaults.cars_present_fraction <= 1.0):
        raise ValueError("cars_present_fraction must be between 0 and 1")
    if defaults.charge_mode not in {"direct", "smart"}:
        raise ValueError("charge_mode must be 'direct' or 'smart'")

    window = _schedule_mask(index, defaults.charging_schedule)
    dt_h = _step_hours(index)
    p = np.zeros(len(index), dtype=float)

    cars_present = float(defaults.n_cars) * float(defaults.cars_present_fraction)
    soc_delta = max(float(defaults.target_departure_soc_pct) - float(defaults.arrival_soc_pct), 0.0) / 100.0
    energy_per_car_kWh = float(defaults.battery_capacity_kWh) * soc_delta
    daily_energy_kWh = cars_present * energy_per_car_kWh

    p_cap = cars_present * float(defaults.p_charger_max_kW)
    if defaults.p_site_cap_kW is not None:
        p_cap = min(p_cap, float(defaults.p_site_cap_kW))

    if defaults.n_cars <= 0 or p_cap <= 0 or daily_energy_kWh <= 0:
        out = pd.Series(p, index=index, name=name)
        out.attrs.update({
            "mobility_energy_required_kWh": 0.0,
            "mobility_energy_charged_kWh": 0.0,
            "mobility_energy_unserved_kWh": 0.0,
            "mobility_energy_per_car_kWh": energy_per_car_kWh,
            "mobility_unserved_by_day": {},
        })
        return out

    if base_load_kW is None:
        base = pd.Series(0.0, index=index, dtype=float)
    else:
        base = base_load_kW.reindex(index).astype(float).fillna(0.0)

    date_keys = pd.Series(index.date, index=index)
    total_required = 0.0
    total_charged = 0.0
    total_unserved = 0.0
    unserved_by_day = {}

    for day in date_keys[window].unique():
        day_positions = np.flatnonzero(window & (date_keys.to_numpy() == day))
        if len(day_positions) == 0:
            continue

        total_required += daily_energy_kWh
        if defaults.charge_mode == "smart":
            if grid_cap_kW is None or float(grid_cap_kW) <= 0:
                allowed = np.full(len(day_positions), p_cap, dtype=float)
            else:
                headroom = np.clip(float(grid_cap_kW) - base.iloc[day_positions].to_numpy(dtype=float), 0.0, None)
                allowed = np.minimum(p_cap, headroom)

            possible = float(np.sum(allowed * dt_h[day_positions]))
            if possible <= 0:
                total_unserved += daily_energy_kWh
                unserved_by_day[day] = daily_energy_kWh
                continue
            scale = min(1.0, daily_energy_kWh / possible)
            p[day_positions] = allowed * scale
            charged = float(np.sum(p[day_positions] * dt_h[day_positions]))
            unserved = max(daily_energy_kWh - charged, 0.0)
            total_charged += charged
            total_unserved += unserved
            unserved_by_day[day] = unserved
        else:
            remaining = daily_energy_kWh
            for pos in day_positions:
                if remaining <= 1e-9:
                    break
                step_energy_cap = p_cap * dt_h[pos]
                charge_energy = min(step_energy_cap, remaining)
                p[pos] = charge_energy / dt_h[pos] if dt_h[pos] > 0 else 0.0
                remaining -= charge_energy
            charged = daily_energy_kWh - max(remaining, 0.0)
            total_charged += charged
            unserved = max(remaining, 0.0)
            total_unserved += unserved
            unserved_by_day[day] = unserved

    out = pd.Series(p, index=index, name=name)
    out.attrs.update({
        "mobility_energy_required_kWh": total_required,
        "mobility_energy_charged_kWh": total_charged,
        "mobility_energy_unserved_kWh": total_unserved,
        "mobility_energy_per_car_kWh": energy_per_car_kWh,
        "mobility_unserved_by_day": unserved_by_day,
    })
    return out
