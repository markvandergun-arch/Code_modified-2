# src/load/profiles.py
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Dict, Optional, Tuple




# =============================================================================
# Standard output schema (single source of truth for later phases)
# =============================================================================

STANDARD_OUTPUT_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "electricity": (
        "P_electric_base_load_kW",
        "P_heat_ref_el_kW",
        "P_cool_el_kW",
        "P_hp_el_kW",
        "P_load_total_kW",
        "P_pv_kW",
        "P_wkk_el_kW",
        "P_battery_charge_kW",
        "P_battery_discharge_kW",
        "P_grid_import_kW",
        "P_grid_export_kW",
        "P_net_kW",
    ),
    "heat": (
        "Q_heat_demand_kWth",
        "Q_space_heat_demand_kWth",
        "Q_hp_th_kWth",
        "Q_wkk_used_kWth",
        "Q_wkk_dumped_kWth",
        "Q_thermal_storage_charge_kWth",
        "Q_thermal_storage_discharge_kWth",
        "Q_boiler_th_kWth",
        "Q_dh_th_kWth",
        "Q_heat_from_reference_kWth",
        "Q_heat_supply_total_kWth",
        "Q_heat_unserved_final_kWth",
        "heat_balance_residual_kWth",
    ),
    "fuel": (
        "F_wkk_fuel_kW",
        "F_boiler_fuel_kW",
        "F_total_fuel_kW",
        "F_total_gas_kW",
    ),
    "evaluation": (
        "P_contract_limit_kW",
        "P_grid_contract_excess_kW",
        "grid_contract_exceeded",
    ),
}


DEFAULT_STOPLIGHT_THRESHOLDS: Dict[str, float] = {
    "green_peak_ratio_max": 0.95,
    "orange_peak_ratio_max": 1.00,
    "red_peak_ratio_min": 1.00,
    "orange_p99_ratio_max": 0.95,
    "max_exceedance_duration_h": 0.0,
    "max_exceedance_energy_kWh": 0.0,
}

# =============================================================================
# Enums
# =============================================================================

class BuildingType(str, Enum):
    OFFICE = "kantoor"
    HOSPITAL = "ziekenhuis"
    SCHOOL = "school"
    POLICE = "politiebureau"


class YearClass(str, Enum):
    PRE_1992 = "pre_1992"
    Y1992_2005 = "1992_2005"
    Y2006_2014 = "2006_2014"
    Y2015_PLUS = "2015_plus"


class Orientation8(str, Enum):
    N = "N"
    NE = "NE"
    E = "E"
    SE = "SE"
    S = "S"
    SW = "SW"
    W = "W"
    NW = "NW"


class BuildingShape(str, Enum):
    """
    Discrete geometry "compactness" choices, mapped to a shape_factor.

    - COMPACT: relatively compact rectangle / small perimeter per footprint
    - RECTANGULAR: typical rectangular office/school
    - L_SHAPE: less compact (more facade per floor area)
    - SPRAWLING: very non-compact / lots of facade
    """
    COMPACT = "compact"
    RECTANGULAR = "rectangular"
    L_SHAPE = "l_shape"
    SPRAWLING = "sprawling"


class Season(str, Enum):
    WINTER = "winter"
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"


# =============================================================================
# Schedule model (kept intentionally simple for v1)
# =============================================================================

@dataclass(frozen=True)
class WeeklySchedule:
    """
    Very simple weekly schedule.

    - days_active: tuple of weekday indices (Mon=0 ... Sun=6) when schedule is active
    - start_hour: inclusive
    - end_hour: exclusive

    Example: office Mon-Fri 08:00-18:00 -> days_active=(0,1,2,3,4), start_hour=8, end_hour=18
    """
    days_active: Tuple[int, ...]
    start_hour: int
    end_hour: int

    def validate(self) -> None:
        if not self.days_active:
            raise ValueError("days_active must not be empty.")
        if any(d < 0 or d > 6 for d in self.days_active):
            raise ValueError("days_active must be weekday indices 0..6 (Mon..Sun).")
        if not (0 <= self.start_hour <= 23 and 0 <= self.end_hour <= 24):
            raise ValueError("start_hour must be 0..23 and end_hour must be 0..24.")
        if self.end_hour <= self.start_hour:
            raise ValueError("end_hour must be > start_hour.")


# =============================================================================
# Sub-load models (for future multi-load UI; safe to add now)
# =============================================================================

@dataclass(frozen=True)
class ProcessSubLoad:
    """
    One process with its own weekly schedule and two power levels.
    """
    name: str
    p_process_kW: float
    p_idle_kW: float
    schedule: WeeklySchedule


@dataclass(frozen=True)
class OtherSubLoad:
    """
    One "other" (overig) load with its own schedule and two intensities (occupied/unoccupied).
    Intensity is per m2 floor area (consistent with SimpleOccLoadDefaults).
    """
    name: str
    p_occ_W_per_m2: float
    p_unocc_W_per_m2: float
    schedule: WeeklySchedule


# =============================================================================
# Core archetype + load configs
# =============================================================================

@dataclass(frozen=True)
class BuildingArchetype:
    """
    Parameters that drive the thermal building model and schedules.
    Units are intentionally explicit in field names.
    """

    # Geometry shaping inputs used to derive default envelope areas (also useful for reporting/overrides)
    window_to_wall_ratio: float
    shape_factor: float
    floors: int

    # Geometry / envelope areas
    bvo_m2: float
    a_wall_m2: float
    a_roof_m2: float
    a_ground_m2: float
    a_window_m2: float

    # Envelope U-values [W/m2K]
    u_wall_W_m2K: float
    u_roof_W_m2K: float
    u_ground_W_m2K: float
    u_window_W_m2K: float

    # Infiltration proxy (as used in many simplified tools)
    # qv10 in m3/h per m2 of envelope area used for leakage (often A_wall + A_roof)
    qv10_m3ph_per_m2: float
    a_env_for_qv10_m2: float

    # Ventilation flow in occupied/unoccupied state [m3/h]
    vdot_vent_m3ph_occ: float
    vdot_vent_m3ph_unocc: float

    # Heat recovery efficiency (0..1)
    eta_wtw: float

    # Internal gains [W/m2 floor area] in occupied / unoccupied
    q_int_W_per_m2_occ: float
    q_int_W_per_m2_unocc: float

    # Solar gains (simple)
    g_value: float              # glazing solar heat gain coefficient (approx)
    shading_factor: float       # 0..1

    # -------------------------------------------------------------------------
    # Setpoints [°C]
    # New: separate occupied vs unoccupied setpoints
    # Backwards compatibility: keep the old scalar names (occupied defaults).
    # -------------------------------------------------------------------------
    t_heat_set_occ_C: float
    t_heat_set_unocc_C: float
    t_cool_set_occ_C: float
    t_cool_set_unocc_C: float

    # Backwards compatible legacy fields (currently used by gebouwmodel.py)
    t_heat_set_C: float
    t_cool_set_C: float

    # -------------------------------------------------------------------------
    # HVAC performance
    # Backwards compatibility: keep scalar averages.
    # -------------------------------------------------------------------------
    cop_heat: float
    eer_cool: float

    # Schedules + orientation  (MUST be BEFORE any defaulted fields)
    occupancy_schedule: WeeklySchedule
    orientation: Orientation8

    # Optional seasonal values (defaulted fields must come last)
    seasonal_cop_heat_by_season: Optional[Dict[Season, float]] = None
    seasonal_eer_cool_by_season: Optional[Dict[Season, float]] = None


@dataclass(frozen=True)
class SimpleOccLoadDefaults:
    """
    Generic occupancy-based electric load defaults (used for p_elektro and p_overig).
    """
    p_occ_W_per_m2: float
    p_unocc_W_per_m2: float
    schedule: WeeklySchedule  # usually the occupancy schedule


@dataclass(frozen=True)
class ProcessLoadDefaults:
    """
    Simple process load: constant during process schedule, constant outside.
    Not linked to building type/year in v1 (as per your requirement).
    """
    p_process_kW: float
    p_idle_kW: float
    process_schedule: WeeklySchedule


@dataclass(frozen=True)
class MobilityLoadDefaults:
    """
    Deterministic EV charging model.
    """
    n_cars: int
    p_charger_max_kW: float        # per car
    duty_cycle: float              # fraction of cars simultaneously charging (0..1)
    p_site_cap_kW: Optional[float] # optional cap for mobility load
    charging_schedule: WeeklySchedule
    battery_capacity_kWh: float = 60.0
    arrival_soc_pct: float = 50.0
    target_departure_soc_pct: float = 80.0
    cars_present_fraction: float = 1.0
    charge_mode: str = "smart"     # "direct" | "smart"




@dataclass(frozen=True)
class PVConfig:
    enabled: bool = False
    installed_capacity_kWp: float = 0.0
    tilt_deg: float = 35.0
    azimuth_deg: float = 180.0
    performance_ratio: float = 0.85
    inverter_efficiency: float = 0.98
    temp_coeff_per_C: float = -0.004
    site_cap_kW: Optional[float] = None


@dataclass(frozen=True)
class WKKConfig:
    enabled: bool = False
    p_rated_el_kW: float = 0.0
    min_load_fraction: float = 0.0
    electrical_efficiency: float = 0.40
    thermal_efficiency: float = 0.45
    dispatch_mode: str = "electricity_led"


@dataclass(frozen=True)
class BatteryConfig:
    enabled: bool = False
    capacity_kWh: float = 0.0
    p_charge_max_kW: float = 0.0
    p_discharge_max_kW: float = 0.0
    efficiency_roundtrip: float = 0.92
    soc_init_fraction: float = 0.50
    soc_min_fraction: float = 0.10
    soc_max_fraction: float = 0.90
    dispatch_mode: str = "self_consumption"
    charge_strategy: str = "surplus_only"   # "surplus_only" | "grid_headroom"


@dataclass(frozen=True)
class ThermalStorageConfig:
    enabled: bool = False
    capacity_kWh_th: float = 0.0
    p_charge_max_kW: float = 0.0
    p_discharge_max_kW: float = 0.0
    loss_factor_per_hour: float = 0.0
    soc_init_fraction: float = 0.50
    soc_min_fraction: float = 0.10
    soc_max_fraction: float = 0.90
    charge_priority: int = 1
    discharge_priority: int = 1
    efficiency_charge: float = 0.95
    efficiency_discharge: float = 0.95


@dataclass(frozen=True)
class HeatPumpConfig:
    enabled: bool = False
    capacity_kWth: float = 0.0
    cop_nominal: float = 3.5
    cop_mode: str = "fixed"
    supply_temp_regime: str = "low_temp"
    min_part_load_fraction: float = 0.0
    priority: int = 1
    site_cap_electric_kW: Optional[float] = None
    shared_with_grid_cap: bool = True


@dataclass(frozen=True)
class BoilerConfig:
    enabled: bool = False
    capacity_kWth: float = 0.0
    thermal_efficiency: float = 0.92
    fuel_type: str = "gas"
    min_part_load_fraction: float = 0.0
    priority: int = 3
    is_peak_backup: bool = True


@dataclass(frozen=True)
class DistrictHeatConfig:
    enabled: bool = False
    capacity_kWth: float = 0.0
    tariff_placeholder: float = 0.0
    priority: int = 2


@dataclass(frozen=True)
class HeatSystemConfig:
    heating_dispatch_mode: str = "power_min_grid"
    cooling_dispatch_mode: str = "electric"
    wkk_dispatch_mode: str = "electricity_led"
    thermal_storage_strategy: str = "passive"
    source_priority_mode: str = "prefer_hp_then_storage_then_boiler_then_dh"
    reference_heating_enabled: bool = True
    reference_cop_heat_by_season: Optional[Dict[str, float]] = None
    reference_eer_cool_by_season: Optional[Dict[str, float]] = None
    allow_hp_for_space_heat: bool = True
    allow_hp_for_dhw: bool = False
    allow_boiler_for_space_heat: bool = True
    allow_boiler_for_dhw: bool = True
    allow_wkk_for_space_heat: bool = True
    allow_dh_for_space_heat: bool = True
    shared_grid_contract_cap: bool = True
    unserved_heat_allowed: bool = False
    heat_balance_tolerance_kW: float = 1e-6


@dataclass(frozen=True)
class MeasurementConfig:
    enabled: bool = False
    time_resolution: str = "15min"
    expected_resolution: Optional[str] = "15min"
    column_mapping: Optional[Dict[str, str]] = None
    timezone: str = "Europe/Amsterdam"
    power_unit_mode: str = "kW"
    resample_policy: str = "mean_to_hourly"
    gap_fill_method: str = "none"
    comparison_mode: str = "grid_import"


@dataclass(frozen=True)
class EvaluationConfig:
    grid_contract_kW: Optional[float] = None
    stoplight_thresholds: Dict[str, float] | None = None
    peak_percentiles: Tuple[float, float] = (0.95, 0.99)
    calibration_metrics_enabled: bool = False
    max_exceedance_duration_h: float = 0.0
    max_exceedance_energy_kWh: float = 0.0
    robust_green_margin_fraction: float = 0.05

    def __post_init__(self) -> None:
        if self.stoplight_thresholds is None:
            object.__setattr__(self, "stoplight_thresholds", dict(DEFAULT_STOPLIGHT_THRESHOLDS))


@dataclass(frozen=True)
class LoadConfig:
    """
    Container for all load-model configs and energy system assets.
    """
    building: BuildingArchetype
    pelektro: SimpleOccLoadDefaults
    pprocess: ProcessLoadDefaults
    pmobility: MobilityLoadDefaults
    poverig: SimpleOccLoadDefaults
    pv: PVConfig = PVConfig()
    wkk: WKKConfig = WKKConfig()
    battery: BatteryConfig = BatteryConfig()
    thermal_storage: ThermalStorageConfig = ThermalStorageConfig()
    heat_pump: HeatPumpConfig = HeatPumpConfig()
    boiler: BoilerConfig = BoilerConfig()
    district_heat: DistrictHeatConfig = DistrictHeatConfig()
    heat_system: HeatSystemConfig = HeatSystemConfig()
    measurement: MeasurementConfig = MeasurementConfig()
    evaluation: EvaluationConfig = EvaluationConfig()


# =============================================================================
# Shape mapping
# =============================================================================

SHAPE_FACTOR_BY_SHAPE: Dict[BuildingShape, float] = {
    BuildingShape.COMPACT: 0.85,
    BuildingShape.RECTANGULAR: 1.00,
    BuildingShape.L_SHAPE: 1.20,
    BuildingShape.SPRAWLING: 1.45,
}


# =============================================================================
# Orientation factor (8-wind)
# =============================================================================

ORIENTATION_FACTOR_8: Dict[Orientation8, float] = {
    Orientation8.S: 1.00,
    Orientation8.SE: 0.85,
    Orientation8.SW: 0.85,
    Orientation8.E: 0.70,
    Orientation8.W: 0.70,
    Orientation8.NE: 0.55,
    Orientation8.NW: 0.55,
    Orientation8.N: 0.40,
}


# =============================================================================
# Default registries (v1)
# =============================================================================

# --- Year-based defaults (mostly envelope + infiltration + wtw + COP/EER) ---
_DEFAULTS_BY_YEARCLASS: Dict[YearClass, Dict[str, float]] = {
    YearClass.PRE_1992: dict(
        u_wall_W_m2K=0.60,
        u_roof_W_m2K=0.45,
        u_ground_W_m2K=0.50,
        u_window_W_m2K=2.8,
        qv10_m3ph_per_m2=1.5,
        eta_wtw=0.00,
        cop_heat=2.5,
        eer_cool=2.5,
        g_value=0.60,  # older glazing: higher g, typically also worse U
    ),
    YearClass.Y1992_2005: dict(
        u_wall_W_m2K=0.45,
        u_roof_W_m2K=0.30,
        u_ground_W_m2K=0.40,
        u_window_W_m2K=2.2,
        qv10_m3ph_per_m2=1.0,
        eta_wtw=0.50,
        cop_heat=3.0,
        eer_cool=3.0,
        g_value=0.55,
    ),
    YearClass.Y2006_2014: dict(
        u_wall_W_m2K=0.30,
        u_roof_W_m2K=0.20,
        u_ground_W_m2K=0.30,
        u_window_W_m2K=1.6,
        qv10_m3ph_per_m2=0.7,
        eta_wtw=0.70,
        cop_heat=3.5,
        eer_cool=3.2,
        g_value=0.52,
    ),
    YearClass.Y2015_PLUS: dict(
        u_wall_W_m2K=0.20,
        u_roof_W_m2K=0.15,
        u_ground_W_m2K=0.20,
        u_window_W_m2K=1.1,
        qv10_m3ph_per_m2=0.4,
        eta_wtw=0.80,
        cop_heat=4.0,
        eer_cool=3.5,
        g_value=0.50,
    ),
}

# --- Building-type defaults (mostly use + schedules + internal gains + ventilation + setpoints) ---
# Ventilation values below are "per m2" base that later gets multiplied by BVO.
_DEFAULTS_BY_BTYPE: Dict[BuildingType, Dict[str, object]] = {
    BuildingType.OFFICE: dict(
        occupancy_schedule=WeeklySchedule(days_active=(0, 1, 2, 3, 4), start_hour=8, end_hour=18),
        # occupied comfort
        t_heat_set_occ_C=20.0,
        t_cool_set_occ_C=24.0,
        # unoccupied setback/setup (night)
        t_heat_set_unocc_C=16.0,
        t_cool_set_unocc_C=27.0,
        vent_m3ph_per_m2_occ=6.0,
        vent_unocc_fraction=0.20,
        q_int_W_per_m2_occ=15.0,
        q_int_W_per_m2_unocc=3.0,
        shading_factor=0.80,
    ),
    BuildingType.SCHOOL: dict(
        occupancy_schedule=WeeklySchedule(days_active=(0, 1, 2, 3, 4), start_hour=8, end_hour=16),
        t_heat_set_occ_C=20.0,
        t_cool_set_occ_C=25.0,
        t_heat_set_unocc_C=15.0,
        t_cool_set_unocc_C=28.0,
        vent_m3ph_per_m2_occ=7.0,
        vent_unocc_fraction=0.10,
        q_int_W_per_m2_occ=12.0,
        q_int_W_per_m2_unocc=2.0,
        shading_factor=0.85,
    ),
    BuildingType.HOSPITAL: dict(
        occupancy_schedule=WeeklySchedule(days_active=(0, 1, 2, 3, 4, 5, 6), start_hour=0, end_hour=24),
        t_heat_set_occ_C=21.0,
        t_cool_set_occ_C=24.0,
        # 24/7: keep equal
        t_heat_set_unocc_C=21.0,
        t_cool_set_unocc_C=24.0,
        vent_m3ph_per_m2_occ=10.0,
        vent_unocc_fraction=0.70,
        q_int_W_per_m2_occ=20.0,
        q_int_W_per_m2_unocc=12.0,
        shading_factor=0.70,
    ),
    BuildingType.POLICE: dict(
        occupancy_schedule=WeeklySchedule(days_active=(0, 1, 2, 3, 4, 5, 6), start_hour=0, end_hour=24),
        t_heat_set_occ_C=20.0,
        t_cool_set_occ_C=24.0,
        # 24/7: keep equal for now
        t_heat_set_unocc_C=20.0,
        t_cool_set_unocc_C=24.0,
        vent_m3ph_per_m2_occ=7.0,
        vent_unocc_fraction=0.50,
        q_int_W_per_m2_occ=18.0,
        q_int_W_per_m2_unocc=8.0,
        shading_factor=0.75,
    ),
}

# --- p_elektro defaults per building type (year factor applied) ---
_PELEKTRO_BY_BTYPE: Dict[BuildingType, Dict[str, float]] = {
    BuildingType.OFFICE: dict(p_occ_W_per_m2=12.0, p_unocc_W_per_m2=3.0),
    BuildingType.SCHOOL: dict(p_occ_W_per_m2=8.0, p_unocc_W_per_m2=1.5),
    BuildingType.HOSPITAL: dict(p_occ_W_per_m2=18.0, p_unocc_W_per_m2=12.0),
    BuildingType.POLICE: dict(p_occ_W_per_m2=14.0, p_unocc_W_per_m2=8.0),
}

# --- p_overig defaults per building type (small background items) ---
_POVERIG_BY_BTYPE: Dict[BuildingType, Dict[str, float]] = {
    BuildingType.OFFICE: dict(p_occ_W_per_m2=2.0, p_unocc_W_per_m2=0.5),
    BuildingType.SCHOOL: dict(p_occ_W_per_m2=1.5, p_unocc_W_per_m2=0.3),
    BuildingType.HOSPITAL: dict(p_occ_W_per_m2=3.0, p_unocc_W_per_m2=2.0),
    BuildingType.POLICE: dict(p_occ_W_per_m2=2.5, p_unocc_W_per_m2=1.5),
}

# --- Year efficiency factor for electric intensity (lighting etc.) ---
_YEAR_ELEC_FACTOR: Dict[YearClass, float] = {
    YearClass.PRE_1992: 1.15,
    YearClass.Y1992_2005: 1.05,
    YearClass.Y2006_2014: 1.00,
    YearClass.Y2015_PLUS: 0.90,
}


# =============================================================================
# Seasonal performance defaults (simple; can be overridden)
# =============================================================================

def default_seasonal_performance(year_class: YearClass) -> tuple[Dict[Season, float], Dict[Season, float]]:
    """
    Create simple seasonal COP/EER curves around the year-class base values.

    Rationale (very simplified):
    - Heating COP is typically lower in winter (colder source) and higher in milder seasons.
    - Cooling EER can be slightly lower in hotter summer conditions.

    These are *defaults* only; user can override per season in the UI.
    """
    y = _DEFAULTS_BY_YEARCLASS[year_class]
    base_cop = float(y["cop_heat"])
    base_eer = float(y["eer_cool"])

    cop = {
        Season.WINTER: 0.90 * base_cop,
        Season.SPRING: 1.00 * base_cop,
        Season.SUMMER: 1.10 * base_cop,
        Season.AUTUMN: 1.00 * base_cop,
    }
    eer = {
        Season.WINTER: 1.05 * base_eer,
        Season.SPRING: 1.00 * base_eer,
        Season.SUMMER: 0.90 * base_eer,
        Season.AUTUMN: 1.00 * base_eer,
    }
    return cop, eer


# =============================================================================
# Geometry helper (very simple, override-friendly)
# =============================================================================

def estimate_geometry_from_bvo(
    bvo_m2: float,
    floors: int = 1,
    window_to_wall_ratio: float = 0.35,
    shape_factor: float = 1.0,
) -> Dict[str, float]:
    """
    Estimate areas from BVO with a simple rectangular-compactness assumption.
    This is intentionally rough; users can override any resulting area.

    - floors: number of floors (affects footprint and hence envelope)
    - window_to_wall_ratio: A_window / A_wall
    - shape_factor: >1 means less compact (more facade per footprint), default 1.0

    Returns:
      dict with keys: a_wall_m2, a_roof_m2, a_ground_m2, a_window_m2, a_env_for_qv10_m2
    """
    if bvo_m2 <= 0:
        raise ValueError("bvo_m2 must be > 0.")
    if floors <= 0:
        raise ValueError("floors must be >= 1.")
    if not (0.05 <= window_to_wall_ratio <= 0.80):
        raise ValueError("window_to_wall_ratio should be between 0.05 and 0.80 for sanity.")
    if shape_factor <= 0:
        raise ValueError("shape_factor must be > 0.")

    footprint_m2 = bvo_m2 / float(floors)

    # Assume roughly square footprint: perimeter ~ 4*sqrt(A)
    perimeter_m = 4.0 * (footprint_m2 ** 0.5)

    # Assume storey height ~ 3.0 m
    storey_h_m = 3.0
    facade_area_m2 = perimeter_m * storey_h_m * float(floors) * shape_factor

    a_wall_m2 = facade_area_m2
    a_roof_m2 = footprint_m2
    a_ground_m2 = footprint_m2
    a_window_m2 = a_wall_m2 * window_to_wall_ratio

    # Use wall + roof as envelope area for qv10 scaling in v1
    a_env_for_qv10_m2 = a_wall_m2 + a_roof_m2

    return dict(
        a_wall_m2=a_wall_m2,
        a_roof_m2=a_roof_m2,
        a_ground_m2=a_ground_m2,
        a_window_m2=a_window_m2,
        a_env_for_qv10_m2=a_env_for_qv10_m2,
    )


# =============================================================================
# Override / merge utilities
# =============================================================================

def _merge_dict(base: Dict, overrides: Optional[Dict]) -> Dict:
    if not overrides:
        return dict(base)
    out = dict(base)
    out.update({k: v for k, v in overrides.items() if v is not None})
    return out


def _validate_archetype(a: BuildingArchetype) -> None:
    # basic sanity checks
    if a.bvo_m2 <= 0:
        raise ValueError("bvo_m2 must be > 0")
    for name in ("a_wall_m2", "a_roof_m2", "a_ground_m2", "a_window_m2", "a_env_for_qv10_m2"):
        if getattr(a, name) <= 0:
            raise ValueError(f"{name} must be > 0")
    for name in ("u_wall_W_m2K", "u_roof_W_m2K", "u_ground_W_m2K", "u_window_W_m2K"):
        if getattr(a, name) <= 0:
            raise ValueError(f"{name} must be > 0")

    if not (0.05 <= a.window_to_wall_ratio <= 0.80):
        raise ValueError("window_to_wall_ratio should be between 0.05 and 0.80.")
    if a.shape_factor <= 0:
        raise ValueError("shape_factor must be > 0.")
    if a.floors <= 0:
        raise ValueError("floors must be >= 1.")

    if not (0.0 <= a.eta_wtw <= 0.95):
        raise ValueError("eta_wtw must be between 0 and 0.95")
    if not (0.1 <= a.g_value <= 0.9):
        raise ValueError("g_value must be between 0.1 and 0.9")
    if not (0.0 <= a.shading_factor <= 1.0):
        raise ValueError("shading_factor must be between 0 and 1")

    # setpoints sanity
    if a.t_cool_set_occ_C <= a.t_heat_set_occ_C:
        raise ValueError("t_cool_set_occ_C should be > t_heat_set_occ_C for typical comfort buildings.")
    if a.t_cool_set_unocc_C <= a.t_heat_set_unocc_C:
        raise ValueError("t_cool_set_unocc_C should be > t_heat_set_unocc_C for typical comfort buildings.")

    # typical setback/setup expectations (not hard physics, but avoids common UI mistakes)
    if a.t_heat_set_unocc_C > a.t_heat_set_occ_C:
        raise ValueError("t_heat_set_unocc_C should be <= t_heat_set_occ_C (setback).")
    if a.t_cool_set_unocc_C < a.t_cool_set_occ_C:
        raise ValueError("t_cool_set_unocc_C should be >= t_cool_set_occ_C (setup).")

    if a.cop_heat <= 0 or a.eer_cool <= 0:
        raise ValueError("cop_heat and eer_cool must be > 0")

    if a.seasonal_cop_heat_by_season is not None:
        for s, v in a.seasonal_cop_heat_by_season.items():
            if v <= 0:
                raise ValueError(f"seasonal COP must be > 0 (season={s}).")
    if a.seasonal_eer_cool_by_season is not None:
        for s, v in a.seasonal_eer_cool_by_season.items():
            if v <= 0:
                raise ValueError(f"seasonal EER must be > 0 (season={s}).")

    a.occupancy_schedule.validate()


# =============================================================================
# Public factory: make defaults + apply overrides
# =============================================================================

def get_standard_output_columns() -> Dict[str, Tuple[str, ...]]:
    """Return a copy of the canonical output schema grouped by carrier."""
    return {group: tuple(cols) for group, cols in STANDARD_OUTPUT_COLUMNS.items()}


def make_default_load_config(
    building_type: BuildingType,
    year_class: YearClass,
    bvo_m2: float,
    orientation: Orientation8 = Orientation8.S,
    *,
    # Geometry shaping inputs (can be left as defaults)
    floors: int = 1,
    window_to_wall_ratio: float = 0.35,
    shape_factor: float = 1.0,
    # Optional overrides (fine-grained)
    building_overrides: Optional[Dict[str, object]] = None,
    pelektro_overrides: Optional[Dict[str, object]] = None,
    pprocess_overrides: Optional[Dict[str, object]] = None,
    pmobility_overrides: Optional[Dict[str, object]] = None,
    poverig_overrides: Optional[Dict[str, object]] = None,
    # Generation + storage overrides
    pv_overrides: Optional[Dict[str, object]] = None,
    wkk_overrides: Optional[Dict[str, object]] = None,
    battery_overrides: Optional[Dict[str, object]] = None,
    thermal_storage_overrides: Optional[Dict[str, object]] = None,
    heat_pump_overrides: Optional[Dict[str, object]] = None,
    boiler_overrides: Optional[Dict[str, object]] = None,
    district_heat_overrides: Optional[Dict[str, object]] = None,
    heat_system_overrides: Optional[Dict[str, object]] = None,
    measurement_overrides: Optional[Dict[str, object]] = None,
    evaluation_overrides: Optional[Dict[str, object]] = None,
    # New: whether to attach seasonal COP/EER defaults
    use_seasonal_cop_eer: bool = True,
) -> LoadConfig:
    """
    Create a fully specified LoadConfig based on (building_type, year_class, BVO, orientation),
    then apply optional overrides.

    Overrides are dicts matching dataclass field names, e.g.:
      building_overrides={"u_wall_W_m2K": 0.25, "t_heat_set_occ_C": 19.0}
      pelektro_overrides={"p_occ_W_per_m2": 10.0}

    Note on geometry shaping overrides:
      window_to_wall_ratio/shape_factor/floors are stored on the archetype.
      Envelope areas are derived *before* applying overrides; if you override the shaping inputs
      you typically also want to re-run this factory so geometry is re-derived.
    """
    if bvo_m2 <= 0:
        raise ValueError("bvo_m2 must be > 0")

    # 1) geometry defaults
    geom = estimate_geometry_from_bvo(
        bvo_m2=bvo_m2,
        floors=floors,
        window_to_wall_ratio=window_to_wall_ratio,
        shape_factor=shape_factor,
    )

    # 2) get year and building type defaults
    y = _DEFAULTS_BY_YEARCLASS[year_class]
    t = _DEFAULTS_BY_BTYPE[building_type]

    occ_sched: WeeklySchedule = t["occupancy_schedule"]
    occ_sched.validate()

    vent_m3ph_per_m2_occ = float(t["vent_m3ph_per_m2_occ"])
    vent_unocc_fraction = float(t["vent_unocc_fraction"])

    vdot_vent_occ = vent_m3ph_per_m2_occ * bvo_m2
    vdot_vent_unocc = vdot_vent_occ * vent_unocc_fraction

    # 3) Seasonal COP/EER defaults
    seasonal_cop, seasonal_eer = default_seasonal_performance(year_class)

    # 4) Build archetype
    t_heat_occ = float(t["t_heat_set_occ_C"])
    t_heat_unocc = float(t["t_heat_set_unocc_C"])
    t_cool_occ = float(t["t_cool_set_occ_C"])
    t_cool_unocc = float(t["t_cool_set_unocc_C"])

    archetype = BuildingArchetype(
        # shaping inputs (reporting + overrides)
        window_to_wall_ratio=float(window_to_wall_ratio),
        shape_factor=float(shape_factor),
        floors=int(floors),

        # areas
        bvo_m2=bvo_m2,
        a_wall_m2=float(geom["a_wall_m2"]),
        a_roof_m2=float(geom["a_roof_m2"]),
        a_ground_m2=float(geom["a_ground_m2"]),
        a_window_m2=float(geom["a_window_m2"]),

        # U-values / infiltration / ventilation / gains
        u_wall_W_m2K=float(y["u_wall_W_m2K"]),
        u_roof_W_m2K=float(y["u_roof_W_m2K"]),
        u_ground_W_m2K=float(y["u_ground_W_m2K"]),
        u_window_W_m2K=float(y["u_window_W_m2K"]),
        qv10_m3ph_per_m2=float(y["qv10_m3ph_per_m2"]),
        a_env_for_qv10_m2=float(geom["a_env_for_qv10_m2"]),
        vdot_vent_m3ph_occ=float(vdot_vent_occ),
        vdot_vent_m3ph_unocc=float(vdot_vent_unocc),
        eta_wtw=float(y["eta_wtw"]),
        q_int_W_per_m2_occ=float(t["q_int_W_per_m2_occ"]),
        q_int_W_per_m2_unocc=float(t["q_int_W_per_m2_unocc"]),
        g_value=float(y["g_value"]),
        shading_factor=float(t["shading_factor"]),

        # setpoints
        t_heat_set_occ_C=t_heat_occ,
        t_heat_set_unocc_C=t_heat_unocc,
        t_cool_set_occ_C=t_cool_occ,
        t_cool_set_unocc_C=t_cool_unocc,

        # legacy fields (occupied)
        t_heat_set_C=t_heat_occ,
        t_cool_set_C=t_cool_occ,

        # HVAC performance (legacy scalars)
        cop_heat=float(y["cop_heat"]),
        eer_cool=float(y["eer_cool"]),
        seasonal_cop_heat_by_season=(seasonal_cop if use_seasonal_cop_eer else None),
        seasonal_eer_cool_by_season=(seasonal_eer if use_seasonal_cop_eer else None),

        # schedules + orientation
        occupancy_schedule=occ_sched,
        orientation=orientation,
    )

    # Apply building overrides (if any)
    if building_overrides:
        archetype = replace(archetype, **building_overrides)

        # keep legacy fields aligned if user overrides only the new ones
        # (so old gebouwmodel.py remains stable until we update it)
        archetype = replace(
            archetype,
            t_heat_set_C=archetype.t_heat_set_occ_C,
            t_cool_set_C=archetype.t_cool_set_occ_C,
        )

    _validate_archetype(archetype)

    # 5) p_elektro defaults (+ year factor)
    year_factor = _YEAR_ELEC_FACTOR[year_class]
    pe_base = _PELEKTRO_BY_BTYPE[building_type]
    pelektro = SimpleOccLoadDefaults(
        p_occ_W_per_m2=float(pe_base["p_occ_W_per_m2"]) * year_factor,
        p_unocc_W_per_m2=float(pe_base["p_unocc_W_per_m2"]) * year_factor,
        schedule=archetype.occupancy_schedule,
    )
    if pelektro_overrides:
        pelektro = replace(pelektro, **pelektro_overrides)
        pelektro.schedule.validate()

    # 6) processes (not building-type/year dependent in v1)
    default_process_sched = WeeklySchedule(days_active=(0, 1, 2, 3, 4), start_hour=9, end_hour=17)
    default_process_sched.validate()
    pprocess = ProcessLoadDefaults(
        p_process_kW=0.0,
        p_idle_kW=0.0,
        process_schedule=default_process_sched,
    )
    if pprocess_overrides:
        pprocess = replace(pprocess, **pprocess_overrides)
        pprocess.process_schedule.validate()

    # 7) mobility (default: off)
    default_charge_sched = WeeklySchedule(days_active=(0, 1, 2, 3, 4), start_hour=9, end_hour=17)
    default_charge_sched.validate()
    pmobility = MobilityLoadDefaults(
        n_cars=0,
        p_charger_max_kW=11.0,
        duty_cycle=0.3,
        p_site_cap_kW=None,
        charging_schedule=default_charge_sched,
        battery_capacity_kWh=60.0,
        arrival_soc_pct=50.0,
        target_departure_soc_pct=80.0,
        cars_present_fraction=1.0,
        charge_mode="smart",
    )
    if pmobility_overrides:
        pmobility = replace(pmobility, **pmobility_overrides)
        pmobility.charging_schedule.validate()
        if pmobility.n_cars < 0:
            raise ValueError("pmobility.n_cars must be >= 0")
        if not (0.0 <= pmobility.duty_cycle <= 1.0):
            raise ValueError("pmobility.duty_cycle must be between 0 and 1")
        if pmobility.p_charger_max_kW <= 0:
            raise ValueError("pmobility.p_charger_max_kW must be > 0")
        if pmobility.p_site_cap_kW is not None and pmobility.p_site_cap_kW <= 0:
            raise ValueError("pmobility.p_site_cap_kW must be > 0 when provided")
        if pmobility.battery_capacity_kWh < 0:
            raise ValueError("pmobility.battery_capacity_kWh must be >= 0")
        if not (0.0 <= pmobility.arrival_soc_pct <= 100.0):
            raise ValueError("pmobility.arrival_soc_pct must be between 0 and 100")
        if not (0.0 <= pmobility.target_departure_soc_pct <= 100.0):
            raise ValueError("pmobility.target_departure_soc_pct must be between 0 and 100")
        if not (0.0 <= pmobility.cars_present_fraction <= 1.0):
            raise ValueError("pmobility.cars_present_fraction must be between 0 and 1")
        if pmobility.charge_mode not in {"direct", "smart"}:
            raise ValueError("pmobility.charge_mode must be 'direct' or 'smart'")

    # 8) other loads defaults
    po_base = _POVERIG_BY_BTYPE[building_type]
    poverig = SimpleOccLoadDefaults(
        p_occ_W_per_m2=float(po_base["p_occ_W_per_m2"]),
        p_unocc_W_per_m2=float(po_base["p_unocc_W_per_m2"]),
        schedule=archetype.occupancy_schedule,
    )
    if poverig_overrides:
        poverig = replace(poverig, **poverig_overrides)
        poverig.schedule.validate()

    # 9) generation defaults
    pv = PVConfig()
    if pv_overrides:
        pv = replace(pv, **pv_overrides)
        if pv.installed_capacity_kWp < 0:
            raise ValueError("pv.installed_capacity_kWp must be >= 0")
        if not (0.0 <= pv.performance_ratio <= 1.2):
            raise ValueError("pv.performance_ratio must be between 0 and 1.2")
        if not (0.0 <= pv.inverter_efficiency <= 1.0):
            raise ValueError("pv.inverter_efficiency must be between 0 and 1")
        if pv.site_cap_kW is not None and pv.site_cap_kW <= 0:
            raise ValueError("pv.site_cap_kW must be > 0 when provided")

    wkk = WKKConfig()
    if wkk_overrides:
        wkk = replace(wkk, **wkk_overrides)
        if wkk.p_rated_el_kW < 0:
            raise ValueError("wkk.p_rated_el_kW must be >= 0")
        if not (0.0 <= wkk.min_load_fraction <= 1.0):
            raise ValueError("wkk.min_load_fraction must be between 0 and 1")
        if not (0.0 < wkk.electrical_efficiency <= 1.0):
            raise ValueError("wkk.electrical_efficiency must be between 0 and 1")
        if not (0.0 <= wkk.thermal_efficiency <= 1.0):
            raise ValueError("wkk.thermal_efficiency must be between 0 and 1")

    # 10) storage defaults / placeholders
    battery = BatteryConfig()
    if battery_overrides:
        battery = replace(battery, **battery_overrides)
        if battery.capacity_kWh < 0:
            raise ValueError("battery.capacity_kWh must be >= 0")
        if battery.p_charge_max_kW < 0 or battery.p_discharge_max_kW < 0:
            raise ValueError("battery charge/discharge power must be >= 0")
        if not (0.0 <= battery.efficiency_roundtrip <= 1.0):
            raise ValueError("battery.efficiency_roundtrip must be between 0 and 1")

    thermal_storage = ThermalStorageConfig()
    if thermal_storage_overrides:
        thermal_storage = replace(thermal_storage, **thermal_storage_overrides)
        if thermal_storage.capacity_kWh_th < 0:
            raise ValueError("thermal_storage.capacity_kWh_th must be >= 0")
        if thermal_storage.p_charge_max_kW < 0 or thermal_storage.p_discharge_max_kW < 0:
            raise ValueError("thermal_storage charge/discharge power must be >= 0")
        if not (0.0 <= thermal_storage.loss_factor_per_hour <= 1.0):
            raise ValueError("thermal_storage.loss_factor_per_hour must be between 0 and 1")
        if not (0.0 <= thermal_storage.soc_min_fraction <= thermal_storage.soc_init_fraction <= thermal_storage.soc_max_fraction <= 1.0):
            raise ValueError("thermal_storage soc fractions must satisfy 0 <= min <= init <= max <= 1")
        if thermal_storage.charge_priority < 0 or thermal_storage.discharge_priority < 0:
            raise ValueError("thermal_storage priorities must be >= 0")
        if not (0.0 < thermal_storage.efficiency_charge <= 1.0):
            raise ValueError("thermal_storage.efficiency_charge must be between 0 and 1")
        if not (0.0 < thermal_storage.efficiency_discharge <= 1.0):
            raise ValueError("thermal_storage.efficiency_discharge must be between 0 and 1")

    heat_pump = HeatPumpConfig()
    if heat_pump_overrides:
        heat_pump = replace(heat_pump, **heat_pump_overrides)
        if heat_pump.capacity_kWth < 0:
            raise ValueError("heat_pump.capacity_kWth must be >= 0")
        if heat_pump.cop_nominal <= 0:
            raise ValueError("heat_pump.cop_nominal must be > 0")
        if not (0.0 <= heat_pump.min_part_load_fraction <= 1.0):
            raise ValueError("heat_pump.min_part_load_fraction must be between 0 and 1")
        if heat_pump.site_cap_electric_kW is not None and heat_pump.site_cap_electric_kW <= 0:
            raise ValueError("heat_pump.site_cap_electric_kW must be > 0 when provided")
        if heat_pump.priority < 0:
            raise ValueError("heat_pump.priority must be >= 0")

    boiler = BoilerConfig()
    if boiler_overrides:
        boiler = replace(boiler, **boiler_overrides)
        if boiler.capacity_kWth < 0:
            raise ValueError("boiler.capacity_kWth must be >= 0")
        if not (0.0 < boiler.thermal_efficiency <= 1.0):
            raise ValueError("boiler.thermal_efficiency must be between 0 and 1")
        if not (0.0 <= boiler.min_part_load_fraction <= 1.0):
            raise ValueError("boiler.min_part_load_fraction must be between 0 and 1")
        if boiler.priority < 0:
            raise ValueError("boiler.priority must be >= 0")

    district_heat = DistrictHeatConfig()
    if district_heat_overrides:
        district_heat = replace(district_heat, **district_heat_overrides)
        if district_heat.capacity_kWth < 0:
            raise ValueError("district_heat.capacity_kWth must be >= 0")
        if district_heat.tariff_placeholder < 0:
            raise ValueError("district_heat.tariff_placeholder must be >= 0")
        if district_heat.priority < 0:
            raise ValueError("district_heat.priority must be >= 0")

    heat_system = HeatSystemConfig()
    if heat_system_overrides:
        heat_system = replace(heat_system, **heat_system_overrides)
        if not heat_system.heating_dispatch_mode:
            raise ValueError("heat_system.heating_dispatch_mode must not be empty")
        if not heat_system.cooling_dispatch_mode:
            raise ValueError("heat_system.cooling_dispatch_mode must not be empty")
        if not heat_system.wkk_dispatch_mode:
            raise ValueError("heat_system.wkk_dispatch_mode must not be empty")
        if not heat_system.thermal_storage_strategy:
            raise ValueError("heat_system.thermal_storage_strategy must not be empty")
        if heat_system.heat_balance_tolerance_kW < 0:
            raise ValueError("heat_system.heat_balance_tolerance_kW must be >= 0")
        for label, values in (
            ("reference_cop_heat_by_season", heat_system.reference_cop_heat_by_season),
            ("reference_eer_cool_by_season", heat_system.reference_eer_cool_by_season),
        ):
            if values is not None:
                for season, value in values.items():
                    if float(value) <= 0:
                        raise ValueError(f"heat_system.{label} must contain positive values (season={season}).")

    measurement = MeasurementConfig()
    if measurement_overrides:
        measurement = replace(measurement, **measurement_overrides)
        if not measurement.time_resolution:
            raise ValueError("measurement.time_resolution must not be empty")
        if not measurement.timezone:
            raise ValueError("measurement.timezone must not be empty")
        if measurement.column_mapping is not None and not isinstance(measurement.column_mapping, dict):
            raise ValueError("measurement.column_mapping must be a dict or None")
        if measurement.power_unit_mode not in {"kW", "kWh_per_interval"}:
            raise ValueError("measurement.power_unit_mode must be 'kW' or 'kWh_per_interval'")
        if not measurement.resample_policy:
            raise ValueError("measurement.resample_policy must not be empty")

    evaluation = EvaluationConfig()
    if evaluation_overrides:
        evaluation = replace(evaluation, **evaluation_overrides)
        if evaluation.grid_contract_kW is not None and evaluation.grid_contract_kW <= 0:
            raise ValueError("evaluation.grid_contract_kW must be > 0 when provided")
        if len(evaluation.peak_percentiles) != 2:
            raise ValueError("evaluation.peak_percentiles must contain exactly 2 values")
        if evaluation.max_exceedance_duration_h < 0:
            raise ValueError("evaluation.max_exceedance_duration_h must be >= 0")
        if evaluation.max_exceedance_energy_kWh < 0:
            raise ValueError("evaluation.max_exceedance_energy_kWh must be >= 0")
        if not (0.0 <= evaluation.robust_green_margin_fraction <= 1.0):
            raise ValueError("evaluation.robust_green_margin_fraction must be between 0 and 1")
        if not isinstance(evaluation.stoplight_thresholds, dict):
            raise ValueError("evaluation.stoplight_thresholds must be a dict")
        p1, p2 = evaluation.peak_percentiles
        if not (0.0 <= p1 <= 1.0 and 0.0 <= p2 <= 1.0 and p1 <= p2):
            raise ValueError("evaluation.peak_percentiles must satisfy 0 <= p1 <= p2 <= 1")

    return LoadConfig(
        building=archetype,
        pelektro=pelektro,
        pprocess=pprocess,
        pmobility=pmobility,
        poverig=poverig,
        pv=pv,
        wkk=wkk,
        battery=battery,
        thermal_storage=thermal_storage,
        heat_pump=heat_pump,
        boiler=boiler,
        district_heat=district_heat,
        heat_system=heat_system,
        measurement=measurement,
        evaluation=evaluation,
    )
