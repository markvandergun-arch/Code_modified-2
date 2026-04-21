from __future__ import annotations

import numpy as np
import pandas as pd


_ALLOWED_COP_MODES = {"fixed", "seasonal", "weather_dependent"}


def _resolve_cop(index: pd.DatetimeIndex, config, demand_df: pd.DataFrame) -> np.ndarray:
    mode = str(getattr(config, "cop_mode", "fixed") or "fixed").strip().lower()
    if mode not in _ALLOWED_COP_MODES:
        raise ValueError(f"Unsupported heat pump cop_mode='{mode}'. Allowed: {sorted(_ALLOWED_COP_MODES)}")

    cop_nominal = float(getattr(config, "cop_nominal", 3.5))
    if cop_nominal <= 0:
        raise ValueError("config.cop_nominal must be > 0")

    if mode == "fixed":
        return np.full(len(index), cop_nominal, dtype=float)

    if mode == "seasonal":
        months = index.month.to_numpy()
        cop = np.full(len(index), cop_nominal, dtype=float)
        winter = np.isin(months, [12, 1, 2])
        spring = np.isin(months, [3, 4, 5])
        summer = np.isin(months, [6, 7, 8])
        autumn = np.isin(months, [9, 10, 11])
        cop[winter] = 0.90 * cop_nominal
        cop[spring] = 1.00 * cop_nominal
        cop[summer] = 1.10 * cop_nominal
        cop[autumn] = 1.00 * cop_nominal
        return np.clip(cop, 0.1, None)

    # weather_dependent
    if "T_amb_C" in demand_df.columns:
        t_amb = demand_df["T_amb_C"].to_numpy(dtype=float)
    else:
        t_amb = np.full(len(index), 7.0, dtype=float)

    # simple linear proxy around nominal operating point
    # colder ambient -> lower COP, milder ambient -> higher COP
    cop = cop_nominal + 0.06 * (t_amb - 7.0)
    return np.clip(cop, 1.0, None)


def dispatch_heat_pump(index: pd.DatetimeIndex, config, demand_df: pd.DataFrame) -> pd.DataFrame:
    """
    Dispatch a heat pump against explicit thermal demand.

    Expected optional demand columns:
      - Q_heat_unserved_kWth
      - Q_heat_demand_kWth
      - Q_heat_kWth
      - P_grid_headroom_kW
      - P_contract_headroom_kW
      - T_amb_C

    Returned columns:
      - Q_hp_th_kWth
      - P_hp_el_kW
      - Q_hp_unserved_after_hp_kWth
      - hp_cop_effective
      - hp_status
      - hp_load_fraction
      - hp_dispatch_limited_by_grid
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a pandas.DatetimeIndex")
    if not isinstance(demand_df, pd.DataFrame):
        raise TypeError("demand_df must be a pandas.DataFrame")
    if len(index) != len(demand_df.index):
        raise ValueError("index and demand_df must have the same length")

    enabled = bool(getattr(config, "enabled", False))
    q_capacity = float(getattr(config, "capacity_kWth", 0.0))
    min_frac = float(getattr(config, "min_part_load_fraction", 0.0))
    shared_with_grid_cap = bool(getattr(config, "shared_with_grid_cap", True))
    site_cap_electric_kW = getattr(config, "site_cap_electric_kW", None)

    if q_capacity < 0:
        raise ValueError("config.capacity_kWth must be >= 0")
    if not (0.0 <= min_frac <= 1.0):
        raise ValueError("config.min_part_load_fraction must be between 0 and 1")
    if site_cap_electric_kW is not None and float(site_cap_electric_kW) <= 0:
        raise ValueError("config.site_cap_electric_kW must be > 0 when provided")

    zeros = np.zeros(len(index), dtype=float)
    if (not enabled) or q_capacity <= 0:
        return pd.DataFrame(
            {
                "Q_hp_th_kWth": zeros,
                "P_hp_el_kW": zeros,
                "Q_hp_unserved_after_hp_kWth": _get_heat_demand(demand_df),
                "hp_cop_effective": zeros,
                "hp_status": zeros.astype(int),
                "hp_load_fraction": zeros,
                "hp_dispatch_limited_by_grid": zeros.astype(int),
            },
            index=index,
        )

    heat_demand = _get_heat_demand(demand_df)
    cop = _resolve_cop(index, config, demand_df)

    q_target = np.minimum(np.clip(heat_demand, 0.0, None), q_capacity)
    p_required = q_target / cop

    limited_by_grid = np.zeros(len(index), dtype=int)

    if shared_with_grid_cap:
        headroom = _get_optional_series(demand_df, ["P_grid_headroom_kW", "P_contract_headroom_kW"], default=np.inf)
        p_required = np.minimum(p_required, headroom)
        limited_by_grid = (p_required < (q_target / cop) - 1e-9).astype(int)

    if site_cap_electric_kW is not None:
        p_required = np.minimum(p_required, float(site_cap_electric_kW))

    q_delivered = p_required * cop
    q_delivered = np.minimum(q_delivered, q_capacity)

    if min_frac > 0:
        q_min = q_capacity * min_frac
        on_mask = q_delivered >= q_min
        q_delivered = np.where(on_mask, q_delivered, 0.0)
        p_required = np.where(on_mask, p_required, 0.0)

    q_unserved = np.clip(heat_demand - q_delivered, 0.0, None)
    status = (q_delivered > 0).astype(int)
    load_fraction = np.where(q_capacity > 0, q_delivered / q_capacity, 0.0)

    return pd.DataFrame(
        {
            "Q_hp_th_kWth": q_delivered.astype(float),
            "P_hp_el_kW": p_required.astype(float),
            "Q_hp_unserved_after_hp_kWth": q_unserved.astype(float),
            "hp_cop_effective": cop.astype(float),
            "hp_status": status.astype(int),
            "hp_load_fraction": load_fraction.astype(float),
            "hp_dispatch_limited_by_grid": limited_by_grid.astype(int),
        },
        index=index,
    )


def _get_optional_series(demand_df: pd.DataFrame, candidates: list[str], default: float) -> np.ndarray:
    for col in candidates:
        if col in demand_df.columns:
            arr = demand_df[col].to_numpy(dtype=float)
            return np.where(np.isnan(arr), default, arr)
    return np.full(len(demand_df.index), float(default), dtype=float)


def _get_heat_demand(demand_df: pd.DataFrame) -> np.ndarray:
    for col in ["Q_heat_unserved_kWth", "Q_heat_demand_kWth", "Q_heat_kWth"]:
        if col in demand_df.columns:
            return np.clip(demand_df[col].to_numpy(dtype=float), 0.0, None)
    return np.zeros(len(demand_df.index), dtype=float)
