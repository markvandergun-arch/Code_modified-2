from __future__ import annotations

import numpy as np
import pandas as pd


def simulate_thermal_storage(index: pd.DatetimeIndex, config, balance_df: pd.DataFrame) -> pd.DataFrame:
    """
    Real thermal storage model with SoC, charge/discharge limits, standing losses,
    and explicit heat surplus / deficit interaction.

    Expected optional balance columns:
      - Q_heat_surplus_kWth
      - Q_heat_unserved_after_supply_kWth
      - Q_heat_unserved_kWth
      - Q_heat_demand_kWth
      - Q_heat_kWth

    Returned columns:
      - Q_thermal_storage_charge_kWth
      - Q_thermal_storage_discharge_kWth
      - E_thermal_storage_kWhth
      - soc_thermal_storage_fraction
      - Q_heat_unserved_after_storage_kWth
      - Q_heat_surplus_after_storage_kWth
      - Q_thermal_storage_loss_kWth
      - thermal_storage_status
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a pandas.DatetimeIndex")
    if not isinstance(balance_df, pd.DataFrame):
        raise TypeError("balance_df must be a pandas.DataFrame")
    if len(index) != len(balance_df.index):
        raise ValueError("index and balance_df must have the same length")
    if len(index) == 0:
        raise ValueError("index must not be empty")

    enabled = bool(getattr(config, "enabled", False))
    capacity = float(getattr(config, "capacity_kWh_th", 0.0))
    p_charge_max = float(getattr(config, "p_charge_max_kW", 0.0))
    p_discharge_max = float(getattr(config, "p_discharge_max_kW", 0.0))
    loss_factor_per_hour = float(getattr(config, "loss_factor_per_hour", 0.0))
    soc_init_fraction = float(getattr(config, "soc_init_fraction", 0.50))
    soc_min_fraction = float(getattr(config, "soc_min_fraction", 0.10))
    soc_max_fraction = float(getattr(config, "soc_max_fraction", 0.90))
    eff_charge = float(getattr(config, "efficiency_charge", 0.95))
    eff_discharge = float(getattr(config, "efficiency_discharge", 0.95))

    if capacity < 0:
        raise ValueError("config.capacity_kWh_th must be >= 0")
    if p_charge_max < 0 or p_discharge_max < 0:
        raise ValueError("config charge/discharge power must be >= 0")
    if not (0.0 <= loss_factor_per_hour <= 1.0):
        raise ValueError("config.loss_factor_per_hour must be between 0 and 1")
    if not (0.0 <= soc_min_fraction <= soc_init_fraction <= soc_max_fraction <= 1.0):
        raise ValueError("config soc fractions must satisfy 0 <= min <= init <= max <= 1")
    if not (0.0 < eff_charge <= 1.0):
        raise ValueError("config.efficiency_charge must be between 0 and 1")
    if not (0.0 < eff_discharge <= 1.0):
        raise ValueError("config.efficiency_discharge must be between 0 and 1")

    n = len(index)
    zeros = np.zeros(n, dtype=float)

    heat_surplus = _get_optional_series(balance_df, ["Q_heat_surplus_kWth"], default=0.0)
    heat_surplus = np.clip(heat_surplus, 0.0, None)

    heat_deficit = _get_optional_series(
        balance_df,
        ["Q_heat_unserved_after_supply_kWth", "Q_heat_unserved_kWth", "Q_heat_demand_kWth", "Q_heat_kWth"],
        default=0.0,
    )
    heat_deficit = np.clip(heat_deficit, 0.0, None)

    if (not enabled) or capacity <= 0:
        return pd.DataFrame(
            {
                "Q_thermal_storage_charge_kWth": zeros,
                "Q_thermal_storage_discharge_kWth": zeros,
                "E_thermal_storage_kWhth": zeros,
                "soc_thermal_storage_fraction": zeros,
                "Q_heat_unserved_after_storage_kWth": heat_deficit,
                "Q_heat_surplus_after_storage_kWth": heat_surplus,
                "Q_thermal_storage_loss_kWth": zeros,
                "thermal_storage_status": zeros.astype(int),
            },
            index=index,
        )

    dt_h = (index[1] - index[0]).total_seconds() / 3600.0 if n > 1 else 1.0
    e_min = capacity * soc_min_fraction
    e_max = capacity * soc_max_fraction
    e = capacity * soc_init_fraction

    charge = np.zeros(n, dtype=float)
    discharge = np.zeros(n, dtype=float)
    energy = np.zeros(n, dtype=float)
    soc = np.zeros(n, dtype=float)
    loss_kW = np.zeros(n, dtype=float)
    unserved_after = np.zeros(n, dtype=float)
    surplus_after = np.zeros(n, dtype=float)
    status = np.zeros(n, dtype=int)

    for i in range(n):
        # standing loss at start of timestep
        e_loss = e * loss_factor_per_hour * dt_h
        e = max(0.0, e - e_loss)
        loss_kW[i] = e_loss / dt_h if dt_h > 0 else 0.0

        # charge from thermal surplus
        q_surplus = heat_surplus[i]
        free_capacity = max(0.0, e_max - e)
        q_charge_cap_by_energy = free_capacity / (eff_charge * dt_h) if dt_h > 0 and eff_charge > 0 else 0.0
        q_charge = min(q_surplus, p_charge_max, q_charge_cap_by_energy)
        e += q_charge * eff_charge * dt_h
        charge[i] = q_charge
        surplus_after[i] = max(0.0, q_surplus - q_charge)

        # discharge to cover remaining heat deficit
        q_deficit = heat_deficit[i]
        available_energy = max(0.0, e - e_min)
        q_discharge_cap_by_energy = (available_energy * eff_discharge) / dt_h if dt_h > 0 else 0.0
        q_discharge = min(q_deficit, p_discharge_max, q_discharge_cap_by_energy)
        e -= (q_discharge / eff_discharge) * dt_h if eff_discharge > 0 else 0.0
        discharge[i] = q_discharge
        unserved_after[i] = max(0.0, q_deficit - q_discharge)

        e = min(max(e, 0.0), capacity)
        energy[i] = e
        soc[i] = e / capacity if capacity > 0 else 0.0
        status[i] = int((q_charge > 0) or (q_discharge > 0))

    return pd.DataFrame(
        {
            "Q_thermal_storage_charge_kWth": charge.astype(float),
            "Q_thermal_storage_discharge_kWth": discharge.astype(float),
            "E_thermal_storage_kWhth": energy.astype(float),
            "soc_thermal_storage_fraction": soc.astype(float),
            "Q_heat_unserved_after_storage_kWth": unserved_after.astype(float),
            "Q_heat_surplus_after_storage_kWth": surplus_after.astype(float),
            "Q_thermal_storage_loss_kWth": loss_kW.astype(float),
            "thermal_storage_status": status.astype(int),
        },
        index=index,
    )


def simulate_thermal_storage_placeholder(index: pd.DatetimeIndex, config) -> pd.DataFrame:
    """
    Backward-compatible alias. Existing callers can keep using the old function name,
    but now receive a real thermal storage simulation.
    """
    empty = pd.DataFrame(index=index)
    return simulate_thermal_storage(index, config, empty)


def _get_optional_series(df: pd.DataFrame, candidates: list[str], default: float) -> np.ndarray:
    for col in candidates:
        if col in df.columns:
            arr = df[col].to_numpy(dtype=float)
            return np.where(np.isnan(arr), default, arr)
    return np.full(len(df.index), float(default), dtype=float)
