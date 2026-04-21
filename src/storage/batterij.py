from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _as_efficiencies(efficiency_roundtrip: float) -> tuple[float, float]:
    eff_rt = float(np.clip(efficiency_roundtrip, 1e-9, 1.0))
    eff_leg = math.sqrt(eff_rt)
    return eff_leg, eff_leg


def simulate_battery(index: pd.DatetimeIndex, config, balance_df: pd.DataFrame) -> pd.DataFrame:
    """
    Battery dispatch modes:
    - discharge: always reduce residual import need
    - charge strategy:
        1. surplus_only   -> only charge on local oversupply (negative residual)
        2. grid_headroom  -> also charge from grid if net import stays below contract power

    Required in balance_df:
    - P_residual_before_battery_kW

    Optional in balance_df:
    - P_contract_limit_kW
    """
    zeros = np.zeros(len(index), dtype=float)

    if len(index) == 0:
        return pd.DataFrame(
            {
                "P_battery_charge_kW": zeros,
                "P_battery_discharge_kW": zeros,
                "E_battery_kWh": zeros,
                "battery_soc_pct": zeros,
            },
            index=index,
        )

    if "P_residual_before_battery_kW" not in balance_df.columns:
        raise KeyError("balance_df must contain 'P_residual_before_battery_kW'")

    enabled = bool(getattr(config, "enabled", False))
    capacity_kWh = max(float(getattr(config, "capacity_kWh", 0.0)), 0.0)
    p_charge_max_kW = max(float(getattr(config, "p_charge_max_kW", 0.0)), 0.0)
    p_discharge_max_kW = max(float(getattr(config, "p_discharge_max_kW", 0.0)), 0.0)
    dispatch_mode = str(getattr(config, "dispatch_mode", "self_consumption"))
    charge_strategy = str(getattr(config, "charge_strategy", "surplus_only"))

    if (
        not enabled
        or capacity_kWh <= 0.0
        or (p_charge_max_kW <= 0.0 and p_discharge_max_kW <= 0.0)
        or dispatch_mode != "self_consumption"
    ):
        return pd.DataFrame(
            {
                "P_battery_charge_kW": zeros,
                "P_battery_discharge_kW": zeros,
                "E_battery_kWh": zeros,
                "battery_soc_pct": zeros,
            },
            index=index,
        )

    soc_init_fraction = float(np.clip(getattr(config, "soc_init_fraction", 0.50), 0.0, 1.0))
    soc_min_fraction = float(np.clip(getattr(config, "soc_min_fraction", 0.10), 0.0, 1.0))
    soc_max_fraction = float(np.clip(getattr(config, "soc_max_fraction", 0.90), 0.0, 1.0))

    if soc_max_fraction < soc_min_fraction:
        soc_min_fraction, soc_max_fraction = soc_max_fraction, soc_min_fraction

    soc_init_fraction = float(np.clip(soc_init_fraction, soc_min_fraction, soc_max_fraction))
    eta_charge, eta_discharge = _as_efficiencies(getattr(config, "efficiency_roundtrip", 0.92))

    dt_h = (index[1] - index[0]).total_seconds() / 3600.0 if len(index) > 1 else 1.0
    min_energy_kWh = soc_min_fraction * capacity_kWh
    max_energy_kWh = soc_max_fraction * capacity_kWh
    soc_kWh = soc_init_fraction * capacity_kWh

    charge_kW = np.zeros(len(index), dtype=float)
    discharge_kW = np.zeros(len(index), dtype=float)
    energy_kWh = np.zeros(len(index), dtype=float)
    soc_pct = np.zeros(len(index), dtype=float)

    residual = balance_df["P_residual_before_battery_kW"].to_numpy(dtype=float)

    if "P_contract_limit_kW" in balance_df.columns:
        contract_limit = balance_df["P_contract_limit_kW"].to_numpy(dtype=float)
    else:
        contract_limit = np.full(len(index), np.nan, dtype=float)

    for i, residual_kW in enumerate(residual):
        p_charge = 0.0
        p_discharge = 0.0

        room_kWh = max(max_energy_kWh - soc_kWh, 0.0)
        room_power_kW = room_kWh / (eta_charge * dt_h) if dt_h > 0 and eta_charge > 0 else 0.0

        available_kWh = max(soc_kWh - min_energy_kWh, 0.0)
        available_power_kW = available_kWh * eta_discharge / dt_h if dt_h > 0 else 0.0

        # 1. Ontladen bij importvraag
        if residual_kW > 0.0 and p_discharge_max_kW > 0.0:
            p_discharge = min(residual_kW, p_discharge_max_kW, available_power_kW)
            soc_kWh -= (p_discharge / eta_discharge) * dt_h if eta_discharge > 0 else 0.0

        # 2. Laden volgens gekozen strategie
        if p_charge_max_kW > 0.0 and room_power_kW > 0.0:
            if charge_strategy == "surplus_only":
                if residual_kW < 0.0:
                    oversupply_kW = -residual_kW
                    p_charge = min(oversupply_kW, p_charge_max_kW, room_power_kW)

            elif charge_strategy == "grid_headroom":
                contract_kW = contract_limit[i]
                if np.isfinite(contract_kW):
                    # laad zó dat netto import niet boven contract uitkomt
                    # residual kan positief, nul of negatief zijn
                    headroom_kW = max(contract_kW - residual_kW, 0.0)
                    p_charge = min(headroom_kW, p_charge_max_kW, room_power_kW)
                else:
                    # fallback zonder contract: gedraag je als surplus_only
                    if residual_kW < 0.0:
                        oversupply_kW = -residual_kW
                        p_charge = min(oversupply_kW, p_charge_max_kW, room_power_kW)

            else:
                raise ValueError(f"Unknown charge_strategy: {charge_strategy}")

            soc_kWh += p_charge * eta_charge * dt_h

        soc_kWh = float(np.clip(soc_kWh, min_energy_kWh, max_energy_kWh))
        charge_kW[i] = p_charge
        discharge_kW[i] = p_discharge
        energy_kWh[i] = soc_kWh
        soc_pct[i] = 100.0 * soc_kWh / capacity_kWh if capacity_kWh > 0 else 0.0

    return pd.DataFrame(
        {
            "P_battery_charge_kW": charge_kW,
            "P_battery_discharge_kW": discharge_kW,
            "E_battery_kWh": energy_kWh,
            "battery_soc_pct": soc_pct,
        },
        index=index,
    )