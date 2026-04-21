from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


_DEFAULT_COLUMN_MAPPING = {
    "timestamp": "timestamp",
    "grid_import_kW": "grid_import_kW",
    "grid_export_kW": "grid_export_kW",
    "electric_load_kW": "electric_load_kW",
    "gas_kW": "gas_kW",
    "heat_kWth": "heat_kWth",
}

# Canonical internal names aligned with the rest of the model as much as possible.
_MEASUREMENT_CANONICAL_COLUMNS = {
    "grid_import_kW": "P_grid_import_kW",
    "grid_export_kW": "P_grid_export_kW",
    "electric_load_kW": "P_electric_load_kW",
    "gas_kW": "F_gas_kW",
    "heat_kWth": "Q_heat_kWth",
}

_ALLOWED_GAP_FILL_METHODS = {"none", "ffill", "bfill", "interpolate_time", "zero"}
_ALLOWED_RESAMPLE_POLICIES = {"mean", "sum", "mean_to_hourly", "sum_to_hourly", "none"}

_TIMESTAMP_CANDIDATES = ["timestamp", "Timestamp", "Tijdstip", "Tijd", "DatumTijd", "Datetime", "DateTime"]
_GRID_IMPORT_CANDIDATES = ["grid_import_kW", "Grid Import kW", "Netimport", "Waarde", "Verbruik", "Gesaldeerd verbruik"]
_GRID_EXPORT_CANDIDATES = ["grid_export_kW", "Grid Export kW", "Teruglevering", "Teruglevering (kWh)"]
_GAS_CANDIDATES = ["gas_kW", "Gas kW", "Gas", "Gasverbruik"]
_HEAT_CANDIDATES = ["heat_kWth", "Heat kWth", "Warmte", "Warmteverbruik"]
_ELECTRIC_LOAD_CANDIDATES = ["electric_load_kW", "Electric Load kW", "Elektrisch vermogen", "Load"]


def build_measurement_metadata(
    df: pd.DataFrame,
    *,
    timezone: str,
    power_unit_mode: str = "kW",
    expected_resolution: str | None = None,
    resample_policy: str | None = None,
    source_path: str | None = None,
    original_row_count: int | None = None,
    duplicate_timestamp_count: int = 0,
    mapped_columns: Optional[dict[str, str]] = None,
    warnings: Optional[list[str]] = None,
) -> dict:
    """Return metadata describing a normalized measurement dataset."""
    inferred_resolution = None
    actual_coverage_start = None
    actual_coverage_end = None
    coverage_fraction = None

    if isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 0:
        actual_coverage_start = df.index.min().isoformat()
        actual_coverage_end = df.index.max().isoformat()
    if isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 1:
        diffs = df.index.to_series().diff().dropna()
        if not diffs.empty:
            inferred_resolution = pd.to_timedelta(diffs.mode().iloc[0]).isoformat()

    if expected_resolution and isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 1:
        try:
            expected_index = pd.date_range(df.index.min(), df.index.max(), freq=expected_resolution, tz=df.index.tz)
            if len(expected_index) > 0:
                coverage_fraction = float(len(df.index.unique()) / len(expected_index))
        except Exception:
            coverage_fraction = None

    return {
        "source_path": source_path,
        "timezone": timezone,
        "power_unit_mode": power_unit_mode,
        "expected_resolution": expected_resolution,
        "detected_resolution": inferred_resolution,
        "resample_policy": resample_policy,
        "original_row_count": None if original_row_count is None else int(original_row_count),
        "row_count": int(len(df)),
        "duplicate_timestamp_count": int(duplicate_timestamp_count),
        "coverage_start": actual_coverage_start,
        "coverage_end": actual_coverage_end,
        "coverage_fraction_vs_expected": coverage_fraction,
        "columns": list(df.columns),
        "mapped_columns": dict(mapped_columns or {}),
        "missing_values": {c: int(df[c].isna().sum()) for c in df.columns},
        "warnings": list(warnings or []),
    }



def normalize_measurement_power(
    df: pd.DataFrame,
    *,
    power_unit_mode: str = "kW",
    interval_resolution: str | None = None,
) -> pd.DataFrame:
    """Return measurements as average power in kW / kWth.

    Internal convention:
    - electrical powers in kW
    - gas input in kW (LHV/HHV interpretation left to source semantics)
    - heat in kWth
    """
    if power_unit_mode == "kW":
        return df.copy()
    if power_unit_mode != "kWh_per_interval":
        raise ValueError("power_unit_mode must be 'kW' or 'kWh_per_interval'")

    out = df.copy()
    if interval_resolution is None:
        if len(out.index) > 1:
            dt_h = (out.index[1] - out.index[0]).total_seconds() / 3600.0
        else:
            dt_h = 1.0
    else:
        dt_h = pd.to_timedelta(interval_resolution).total_seconds() / 3600.0
    if dt_h <= 0:
        raise ValueError("interval resolution must be > 0")
    return out / dt_h



def _read_measurement_file(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix in {".csv", ".txt"}:
        attempts = [
            {"sep": None, "engine": "python"},
            {"sep": ";"},
            {"sep": ","},
            {"sep": "	"},
        ]
        last_df = None
        for kwargs in attempts:
            df = pd.read_csv(path, **kwargs)
            last_df = df
            if df.shape[1] > 1:
                return df
        return last_df
    raise ValueError("Unsupported file type. Use CSV or Excel.")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out

def _resolve_existing_column(raw: pd.DataFrame, preferred: str, candidates: list[str]) -> str:
    for col in [preferred] + candidates:
        if col in raw.columns:
            return col
    raise KeyError(f"Geen geldige kolom gevonden. Gezocht: {[preferred] + candidates}")


def _build_source_column_map(raw: pd.DataFrame, resolved_mapping: dict[str, str | None]) -> dict[str, str]:
    source_map: dict[str, str] = {}
    for logical_name, source_name in resolved_mapping.items():
        if logical_name == "timestamp" or source_name is None:
            continue
        canonical = _MEASUREMENT_CANONICAL_COLUMNS.get(logical_name)
        if canonical is not None:
            source_map[canonical] = str(source_name)
    return source_map

def read_measurements(
    path: str | Path,
    *,
    column_mapping: Optional[dict[str, str]] = None,
    timezone: str = "Europe/Amsterdam",
    duplicate_policy: str = "mean",
) -> pd.DataFrame:
    """
    Read measurement data from CSV or Excel and normalize schema.

    Output index: timezone-aware DatetimeIndex
    Output columns use canonical internal names where possible:
      - P_grid_import_kW
      - P_grid_export_kW
      - P_electric_load_kW
      - F_gas_kW
      - Q_heat_kWth
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    mapping = dict(_DEFAULT_COLUMN_MAPPING)
    if column_mapping:
        mapping.update(column_mapping)

    raw = _normalize_columns(_read_measurement_file(path))

    timestamp_col = _resolve_existing_column(
        raw,
        mapping.get("timestamp", "timestamp"),
        _TIMESTAMP_CANDIDATES,
    )

    df = raw.copy()
    resolved_mapping = {
        "timestamp": timestamp_col,
        "grid_import_kW": _resolve_existing_column(raw, mapping.get("grid_import_kW", "grid_import_kW"), _GRID_IMPORT_CANDIDATES) if any(c in raw.columns for c in [mapping.get("grid_import_kW", "grid_import_kW")] + _GRID_IMPORT_CANDIDATES) else None,
        "grid_export_kW": _resolve_existing_column(raw, mapping.get("grid_export_kW", "grid_export_kW"), _GRID_EXPORT_CANDIDATES) if any(c in raw.columns for c in [mapping.get("grid_export_kW", "grid_export_kW")] + _GRID_EXPORT_CANDIDATES) else None,
        "electric_load_kW": _resolve_existing_column(raw, mapping.get("electric_load_kW", "electric_load_kW"), _ELECTRIC_LOAD_CANDIDATES) if any(c in raw.columns for c in [mapping.get("electric_load_kW", "electric_load_kW")] + _ELECTRIC_LOAD_CANDIDATES) else None,
        "gas_kW": _resolve_existing_column(raw, mapping.get("gas_kW", "gas_kW"), _GAS_CANDIDATES) if any(c in raw.columns for c in [mapping.get("gas_kW", "gas_kW")] + _GAS_CANDIDATES) else None,
        "heat_kWth": _resolve_existing_column(raw, mapping.get("heat_kWth", "heat_kWth"), _HEAT_CANDIDATES) if any(c in raw.columns for c in [mapping.get("heat_kWth", "heat_kWth")] + _HEAT_CANDIDATES) else None,
    }
    df["timestamp"] = pd.to_datetime(raw[resolved_mapping["timestamp"]], errors="coerce", dayfirst=True)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    df = df.set_index("timestamp")

    if df.index.tz is None:
        df.index = df.index.tz_localize(timezone, ambiguous=False, nonexistent="shift_forward")
    else:
        df.index = df.index.tz_convert(timezone)

    out = pd.DataFrame(index=df.index)
    for source_key, target_col in _MEASUREMENT_CANONICAL_COLUMNS.items():
        source_col = resolved_mapping.get(source_key)
        if source_col is not None and source_col in df.columns:
            out[target_col] = pd.to_numeric(df[source_col], errors="coerce")

    if duplicate_policy not in {"mean", "sum", "first", "last"}:
        raise ValueError("duplicate_policy must be one of {'mean', 'sum', 'first', 'last'}")
    if out.index.has_duplicates:
        if duplicate_policy == "mean":
            out = out.groupby(level=0).mean()
        elif duplicate_policy == "sum":
            out = out.groupby(level=0).sum()
        elif duplicate_policy == "first":
            out = out.groupby(level=0).first()
        else:
            out = out.groupby(level=0).last()

    out = out.sort_index()
    return out



def apply_gap_fill(df: pd.DataFrame, *, method: str = "none") -> pd.DataFrame:
    """Fill NaNs in a normalized measurement frame using a controlled policy."""
    if method not in _ALLOWED_GAP_FILL_METHODS:
        raise ValueError(f"Unsupported gap_fill_method='{method}'. Allowed: {sorted(_ALLOWED_GAP_FILL_METHODS)}")

    if method == "none":
        return df.copy()
    out = df.copy()
    numeric_cols = [c for c in out.columns if pd.api.types.is_numeric_dtype(out[c])]
    if not numeric_cols:
        return out

    if method == "ffill":
        out[numeric_cols] = out[numeric_cols].ffill()
    elif method == "bfill":
        out[numeric_cols] = out[numeric_cols].bfill()
    elif method == "interpolate_time":
        out[numeric_cols] = out[numeric_cols].interpolate(method="time", limit_direction="both")
    elif method == "zero":
        out[numeric_cols] = out[numeric_cols].fillna(0.0)
    return out



def resample_measurements(df: pd.DataFrame, *, resolution: str = "15min", how: str = "mean") -> pd.DataFrame:
    """Resample normalized measurement data to a target resolution."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("df must have a DatetimeIndex")
    if how == "mean":
        return df.resample(resolution).mean()
    if how == "sum":
        return df.resample(resolution).sum()
    raise ValueError("how must be 'mean' or 'sum'")



def _resolve_resample_method(policy: str) -> tuple[str | None, str | None]:
    if policy not in _ALLOWED_RESAMPLE_POLICIES:
        raise ValueError(f"Unsupported resample_policy='{policy}'. Allowed: {sorted(_ALLOWED_RESAMPLE_POLICIES)}")
    if policy == "mean_to_hourly":
        return "1h", "mean"
    if policy == "sum_to_hourly":
        return "1h", "sum"
    if policy == "mean":
        return None, "mean"
    if policy == "sum":
        return None, "sum"
    return None, None



def prepare_measurements_for_calibration(
    path: str | Path,
    *,
    column_mapping: Optional[dict[str, str]] = None,
    timezone: str = "Europe/Amsterdam",
    resolution: str = "15min",
    how: str = "mean",
    power_unit_mode: str = "kW",
    gap_fill_method: str = "none",
    return_metadata: bool = False,
):
    raw_df, metadata = load_measurement_bundle(
        path,
        column_mapping=column_mapping,
        timezone=timezone,
        expected_resolution=resolution,
        power_unit_mode=power_unit_mode,
        gap_fill_method=gap_fill_method,
        hourly_resample_policy=("mean_to_hourly" if how == "mean" else "sum_to_hourly"),
    )
    if not return_metadata:
        return raw_df["measured_15m"]
    return raw_df["measured_15m"], metadata



def load_measurement_bundle(
    path: str | Path,
    *,
    column_mapping: Optional[dict[str, str]] = None,
    timezone: str = "Europe/Amsterdam",
    expected_resolution: str = "15min",
    power_unit_mode: str = "kW",
    gap_fill_method: str = "none",
    hourly_resample_policy: str = "mean_to_hourly",
    duplicate_policy: str = "mean",
) -> tuple[dict[str, pd.DataFrame], dict]:
    """Load a real upload into a stable backend contract for later UI/validation steps.

    Returns
    -------
    bundle:
        {
            "raw_df": raw normalized measurement frame on original timestamps,
            "measured_15m": normalized 15-minute frame,
            "measured_hourly": normalized hourly frame,
        }
    metadata:
        dict with resolution/coverage/warning information.
    """
    path = Path(path)
    mapped_columns = {
        src: dst
        for src, dst in _MEASUREMENT_CANONICAL_COLUMNS.items()
        if (column_mapping or {}).get(src, _DEFAULT_COLUMN_MAPPING.get(src))
    }
    warnings: list[str] = []

    # Read raw source once to capture duplicate information before aggregation.
    source_raw = _normalize_columns(_read_measurement_file(path))
    original_row_count = len(source_raw)

    timestamp_candidates = ["timestamp", "Timestamp", "Tijdstip", "Tijd", "DatumTijd", "Datetime", "DateTime"]

    timestamp_col = (column_mapping or {}).get("timestamp", _DEFAULT_COLUMN_MAPPING["timestamp"])
    if timestamp_col not in source_raw.columns:
        found = None
        for candidate in timestamp_candidates:
            if candidate in source_raw.columns:
                found = candidate
                break
        if found is None:
            raise KeyError(
                f"Geen timestampkolom gevonden. Beschikbare kolommen: {list(source_raw.columns)}"
            )
        timestamp_col = found

    ts_probe = pd.to_datetime(source_raw[timestamp_col], errors="coerce")
    duplicate_timestamp_count = int(ts_probe.dropna().duplicated().sum())
    if duplicate_timestamp_count > 0:
        warnings.append(f"{duplicate_timestamp_count} duplicate timestamps gevonden; duplicate_policy='{duplicate_policy}' toegepast.")

    resolved_mapping = dict(column_mapping or {})
    resolved_mapping["timestamp"] = timestamp_col

    raw_df = read_measurements(
        path,
        column_mapping=resolved_mapping,
        timezone=timezone,
        duplicate_policy=duplicate_policy,
    )
    raw_df = normalize_measurement_power(raw_df, power_unit_mode=power_unit_mode, interval_resolution=expected_resolution)

    inferred_resolution = pd.infer_freq(raw_df.index) if len(raw_df.index) >= 3 else None
    if inferred_resolution is None and len(raw_df.index) > 1:
        diffs = raw_df.index.to_series().diff().dropna()
        if not diffs.empty:
            inferred_resolution = str(diffs.mode().iloc[0])
    if inferred_resolution is None:
        warnings.append("Bronresolutie kon niet eenduidig worden afgeleid.")

    measured_15m = resample_measurements(raw_df, resolution=expected_resolution, how="mean")
    measured_15m = apply_gap_fill(measured_15m, method=gap_fill_method)

    hourly_resolution, hourly_how = _resolve_resample_method(hourly_resample_policy)
    if hourly_resolution is None or hourly_how is None:
        measured_hourly = measured_15m.copy()
    else:
        measured_hourly = resample_measurements(measured_15m, resolution=hourly_resolution, how=hourly_how)

    if measured_15m.isna().any().any():
        warnings.append("Na resampling bevat measured_15m nog missende waarden.")
    if measured_hourly.isna().any().any():
        warnings.append("Na hourly aggregatie bevat measured_hourly nog missende waarden.")
    if len(measured_15m.index) > 1:
        expected_index = pd.date_range(measured_15m.index.min(), measured_15m.index.max(), freq=expected_resolution, tz=measured_15m.index.tz)
        missing_steps = max(len(expected_index) - len(measured_15m.index), 0)
        if missing_steps > 0:
            warnings.append(f"Dataset mist {missing_steps} verwachte tijdstappen op resolutie {expected_resolution}.")

    metadata = build_measurement_metadata(
        measured_15m,
        timezone=timezone,
        power_unit_mode=power_unit_mode,
        expected_resolution=expected_resolution,
        resample_policy=hourly_resample_policy,
        source_path=str(path),
        original_row_count=original_row_count,
        duplicate_timestamp_count=duplicate_timestamp_count,
        mapped_columns=mapped_columns,
        warnings=warnings,
    )
    metadata["source_columns_by_canonical"] = _build_source_column_map(
        source_raw,
        {
            "grid_import_kW": mapped_columns.get("grid_import_kW"),
            "grid_export_kW": mapped_columns.get("grid_export_kW"),
            "electric_load_kW": mapped_columns.get("electric_load_kW"),
            "gas_kW": mapped_columns.get("gas_kW"),
            "heat_kWth": mapped_columns.get("heat_kWth"),
        },
    )

    bundle = {
        "raw_df": raw_df,
        "measured_15m": measured_15m,
        "measured_hourly": measured_hourly,
    }
    return bundle, metadata
