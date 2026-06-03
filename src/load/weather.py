# src/load/weather.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from pathlib import Path


@dataclass(frozen=True)
class TypicalWeatherConfig:
    """
    Synthetic 'typical NL year' weather configuration.

    This is NOT a meteorological TMY. It is a pragmatic forcing generator for v1:
    - seasonal + diurnal temperature pattern with noise
    - wind speed as positive random process with mild seasonality
    - GHI as clear-sky-like seasonal/diurnal envelope with cloudiness noise

    Later you can replace this with KNMI / TMY inputs, while keeping the same output columns.
    """
    seed: int = 42

    # Temperature model [°C]
    t_mean_annual_C: float = 10.5
    t_season_amp_C: float = 11          # summer-winter swing
    t_diurnal_amp_C: float = 2.5         # day-night swing
    t_noise_std_C: float = 1.2           # random variability

    # Wind model [m/s]
    wind_mean_ms: float = 4.5
    wind_season_amp_ms: float = 1.0
    wind_noise_std_ms: float = 1.5
    wind_min_ms: float = 0.0

    # GHI model [W/m²]
    ghi_clear_sky_peak_summer_Wm2: float = 850.0  # peak around noon in summer
    ghi_cloudiness_mean: float = 0.55             # 0..1 (fraction of clear-sky)
    ghi_cloudiness_std: float = 0.18              # variability
    ghi_cloudiness_min: float = 0.05
    ghi_cloudiness_max: float = 1.00


def make_typical_weather(
    index: pd.DatetimeIndex,
    cfg: Optional[TypicalWeatherConfig] = None,
) -> pd.DataFrame:
    """
    Create a synthetic typical-year weather dataframe with:
      - t_amb_C
      - wind_ms
      - ghi_Wm2

    The index must be timezone-aware and regular (e.g., 15min).
    """
    if cfg is None:
        cfg = TypicalWeatherConfig()

    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a pandas.DatetimeIndex")
    if len(index) == 0:
        raise ValueError("index must not be empty")
    if index.tz is None:
        raise ValueError("index must be timezone-aware (e.g., Europe/Amsterdam)")

    rng = np.random.default_rng(cfg.seed)

    # ---------------------------------------------------------------------
    # Time features
    # ---------------------------------------------------------------------
    doy = index.dayofyear.to_numpy(dtype=float)          # 1..365/366
    hour = (index.hour.to_numpy(dtype=float) + index.minute.to_numpy(dtype=float) / 60.0)  # 0..24
    # seasonal phase (peak summer around day ~200)
    season = np.cos(2.0 * np.pi * (doy - 200.0) / 365.0)  # ~+1 in summer, -1 in winter

    # Diurnal phase: peak temperature mid-afternoon ~15:00
    diurnal = np.cos(2.0 * np.pi * (hour - 15.0) / 24.0)  # +1 around 15:00

    # ---------------------------------------------------------------------
    # Temperature [°C]
    # ---------------------------------------------------------------------
    t_base = cfg.t_mean_annual_C + cfg.t_season_amp_C * season + cfg.t_diurnal_amp_C * diurnal
    t_noise = rng.normal(0.0, cfg.t_noise_std_C, size=len(index))
    t_amb = t_base + t_noise

    # ---------------------------------------------------------------------
    # Wind speed [m/s] (positive, mildly seasonal, noisy)
    # ---------------------------------------------------------------------
    # More wind in winter: invert season (winter ~ +1)
    winterness = -season
    wind_base = cfg.wind_mean_ms + cfg.wind_season_amp_ms * winterness
    wind_noise = rng.normal(0.0, cfg.wind_noise_std_ms, size=len(index))
    wind = np.maximum(cfg.wind_min_ms, wind_base + wind_noise)

    # ---------------------------------------------------------------------
    # GHI [W/m²] (simple clear-sky-like envelope * cloudiness)
    # ---------------------------------------------------------------------
    # Daylight envelope: use cosine bell around noon, clamp at 0.
    # Make summer days longer by modulating the "width" with season.
    # width_hours ~ 8 in winter, ~ 14 in summer (very rough NL-like).
    width_hours = 11.0 + 3.0 * season  # 8..14
    # normalized distance from noon
    dist = np.abs(hour - 12.0)
    daylight = np.clip(1.0 - dist / (width_hours / 2.0), 0.0, 1.0)
    # sharpen curve a bit
    daylight = daylight ** 1.6

    # seasonal peak scaling: much higher in summer
    # map season (-1..+1) to peak multiplier ~0.25..1.0
    peak_mult = 0.25 + 0.75 * (season + 1.0) / 2.0
    ghi_clear = cfg.ghi_clear_sky_peak_summer_Wm2 * peak_mult * daylight

    cloud = rng.normal(cfg.ghi_cloudiness_mean, cfg.ghi_cloudiness_std, size=len(index))
    cloud = np.clip(cloud, cfg.ghi_cloudiness_min, cfg.ghi_cloudiness_max)

    ghi = ghi_clear * cloud

    df = pd.DataFrame(
        {
            "t_amb_C": t_amb.astype(float),
            "wind_ms": wind.astype(float),
            "ghi_Wm2": ghi.astype(float),
        },
        index=index,
    )

    return df

WEATHER_COLUMN_MAP = {
    "Dry Bulb Temperature (C)": "t_amb_C",
    "Wind Speed (m/s)": "wind_ms",
    "Global Horizontal Radiation (Wh/m2)": "ghi_Wm2",
}

def _canonical_year_from_excel(raw: pd.DataFrame) -> int:
    month = pd.to_numeric(raw["Month"], errors="coerce")
    day = pd.to_numeric(raw["Day"], errors="coerce")
    has_feb29 = ((month == 2) & (day == 29)).any()
    return 2020 if has_feb29 else 2021




def read_weather_excel(
    path: str | Path,
    year: int | None = None,
    freq: str | None = None,
    tz: str = "Europe/Amsterdam",
) -> pd.DataFrame:
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Weatherbestand niet gevonden: {path}")

    # 1) Lees Excel ALTIJD eerst in
    raw = pd.read_excel(path)

    raw.columns = [str(c).strip() for c in raw.columns]

    required = [
        "Year",
        "Month",
        "Day",
        "Hour",
        "Dry Bulb Temperature (C)",
        "Global Horizontal Radiation (Wh/m2)",
    ]

    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise ValueError(f"Weather Excel mist verplichte kolommen: {missing}")

    # 2) Bouw timestamp uit Excel-kolommen
    ts = pd.to_datetime(
        dict(
            year=pd.to_numeric(raw["Year"], errors="coerce"),
            month=pd.to_numeric(raw["Month"], errors="coerce"),
            day=pd.to_numeric(raw["Day"], errors="coerce"),
            hour=pd.to_numeric(raw["Hour"], errors="coerce"),
        ),
        errors="coerce",
    )

    raw = raw.copy()
    raw["timestamp"] = ts

    # 3) Hernoem naar interne kolomnamen
    rename_map = {
        "Dry Bulb Temperature (C)": "t_amb_C",
        "Global Horizontal Radiation (Wh/m2)": "ghi_Wm2",
        "Relative Humidity (%)": "rh_pct",
        "Wind Speed (m/s)": "wind_ms",
        "Wind Direction (Degrees)": "wind_dir_deg",
        "Direct Normal Radiation (Wh/m2)": "dni_Wm2",
        "Diffuse Horizontal Radiation (Wh/m2)": "dhi_Wm2",
        "Atmospheric Station Pressure (Pa)": "patm_Pa",
        "Dew Point Temperature (C)": "dewpoint_C",
    }
    raw = raw.rename(columns=rename_map)

    available_weather_cols = [c for c in rename_map.values() if c in raw.columns]
    if not available_weather_cols:
        raise ValueError("Geen bruikbare weather-kolommen gevonden in Excel.")

    # 4) Alleen rijen met geldige timestamp houden
    raw = raw.dropna(subset=["timestamp"]).copy()
    raw = raw.set_index("timestamp").sort_index()

    # Eerst duplicates uit ruwe Excel-tijden verwijderen
    raw = raw[~raw.index.duplicated(keep="first")]

    # 5) Maak kunstmatig jaar:
    # jaartal uit Excel negeren, maanden/dagen/uren chronologisch behouden
    artificial_year = 2021
    new_index = pd.to_datetime(
        {
            "year": artificial_year,
            "month": raw.index.month,
            "day": raw.index.day,
            "hour": raw.index.hour,
        },
        errors="coerce",
    )

    out = raw[available_weather_cols].copy()
    out.index = new_index
    out = out[~out.index.isna()].sort_index()

    # Duplicates die ontstaan doordat meerdere jaren op hetzelfde maand-dag-uur vallen:
    # kies gewoon de eerste, precies volgens jouw eis
    out = out[~out.index.duplicated(keep="first")]

    # Daarna timezone toevoegen
    out.index = out.index.tz_localize(
        tz,
        ambiguous=False,
        nonexistent="shift_forward",
    )

    # Door shift_forward kunnen opnieuw duplicates ontstaan
    out = out[~out.index.duplicated(keep="first")]

    # Alleen rijen met echte Excel-data houden
    out = out.dropna(how="all").sort_index()

    if not out.index.is_unique:
        raise ValueError("Weather index is niet uniek na opschonen.")

    # Geen resample / geen interpolatie / geen synthetische aanvulling
    if freq is not None:
        raise ValueError("freq/resample is niet toegestaan; alleen originele Excel-uren gebruiken.")

    if year is not None:
        raise ValueError("year overschrijven is niet toegestaan; functie maakt zelf een kunstmatig jaar.")

    return out
