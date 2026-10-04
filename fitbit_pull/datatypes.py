"""Registry of Google Health API data types that can be listed.

Keys, JSON field names and filter fields come from the Google Health API v4
discovery document (health.googleapis.com/v4).
"""

from dataclasses import dataclass
from enum import Enum

_SCOPE_PREFIX = "https://www.googleapis.com/auth/googlehealth."

ACTIVITY = _SCOPE_PREFIX + "activity_and_fitness.readonly"
MEASUREMENTS = _SCOPE_PREFIX + "health_metrics_and_measurements.readonly"
SLEEP = _SCOPE_PREFIX + "sleep.readonly"
NUTRITION = _SCOPE_PREFIX + "nutrition.readonly"
ECG = _SCOPE_PREFIX + "ecg.readonly"
IRN = _SCOPE_PREFIX + "irn.readonly"


class TimeKind(Enum):
    """How a data type's filter field expects its timestamp literal."""

    PHYSICAL = "physical"  # RFC-3339 UTC, e.g. 2024-01-01T00:00:00Z
    CIVIL = "civil"  # local wall-clock, e.g. 2024-01-01T00:00:00
    DATE = "date"  # YYYY-MM-DD


@dataclass(frozen=True)
class DataType:
    key: str  # URL path segment, e.g. "heart-rate"
    field: str  # JSON payload field on each data point, e.g. "heartRate"
    filter_field: str  # AIP-160 filter field
    kind: TimeKind
    scope: str
    start_only: bool = False  # API only supports ">=" on this field (ECG)


def _interval(key: str, field: str, snake: str, scope: str = ACTIVITY) -> DataType:
    return DataType(key, field, f"{snake}.interval.start_time", TimeKind.PHYSICAL, scope)


def _sample(key: str, field: str, snake: str, scope: str = MEASUREMENTS) -> DataType:
    return DataType(
        key, field, f"{snake}.sample_time.physical_time", TimeKind.PHYSICAL, scope
    )


def _daily(key: str, field: str, snake: str, scope: str = MEASUREMENTS) -> DataType:
    return DataType(key, field, f"{snake}.date", TimeKind.DATE, scope)


def _civil(key: str, field: str, snake: str, scope: str) -> DataType:
    return DataType(key, field, f"{snake}.interval.civil_start_time", TimeKind.CIVIL, scope)


_ALL = [
    # Activity & fitness
    _interval("steps", "steps", "steps"),
    _interval("distance", "distance", "distance"),
    _interval("floors", "floors", "floors"),
    _interval("altitude", "altitude", "altitude"),
    _interval("active-minutes", "activeMinutes", "active_minutes"),
    _interval("active-zone-minutes", "activeZoneMinutes", "active_zone_minutes"),
    _interval("sedentary-period", "sedentaryPeriod", "sedentary_period"),
    _interval("activity-level", "activityLevel", "activity_level"),
    _interval("swim-lengths-data", "swimLengthsData", "swim_lengths_data"),
    _interval("basal-energy-burned", "basalEnergyBurned", "basal_energy_burned"),
    _interval("active-energy-burned", "activeEnergyBurned", "active_energy_burned"),
    _interval("time-in-heart-rate-zone", "timeInHeartRateZone", "time_in_heart_rate_zone"),
    _civil("exercise", "exercise", "exercise", ACTIVITY),
    # Heart & cardio
    _sample("heart-rate", "heartRate", "heart_rate"),
    _sample("heart-rate-variability", "heartRateVariability", "heart_rate_variability"),
    _daily("daily-resting-heart-rate", "dailyRestingHeartRate", "daily_resting_heart_rate"),
    _daily(
        "daily-heart-rate-variability",
        "dailyHeartRateVariability",
        "daily_heart_rate_variability",
    ),
    _daily("daily-heart-rate-zones", "dailyHeartRateZones", "daily_heart_rate_zones"),
    _sample("vo2-max", "vo2Max", "vo2_max"),
    _sample("run-vo2-max", "runVo2Max", "run_vo2_max"),
    _daily("daily-vo2-max", "dailyVo2Max", "daily_vo2_max"),
    DataType(
        "electrocardiogram",
        "electrocardiogram",
        "electrocardiogram.interval.start_time",
        TimeKind.PHYSICAL,
        ECG,
        start_only=True,
    ),
    _civil(
        "irregular-rhythm-notification",
        "irregularRhythmNotification",
        "irregular_rhythm_notification",
        IRN,
    ),
    # Body & measurements
    _sample("weight", "weight", "weight"),
    _sample("height", "height", "height"),
    _sample("bmi", "bmi", "bmi"),
    _sample("body-fat", "bodyFat", "body_fat"),
    _sample("blood-glucose", "bloodGlucose", "blood_glucose"),
    _sample("core-body-temperature", "coreBodyTemperature", "core_body_temperature"),
    _sample("oxygen-saturation", "oxygenSaturation", "oxygen_saturation"),
    _daily("daily-oxygen-saturation", "dailyOxygenSaturation", "daily_oxygen_saturation"),
    # Respiratory
    _daily("daily-respiratory-rate", "dailyRespiratoryRate", "daily_respiratory_rate"),
    _sample(
        "respiratory-rate-sleep-summary",
        "respiratoryRateSleepSummary",
        "respiratory_rate_sleep_summary",
    ),
    # Sleep: the API filters sleep sessions by end time, not start time.
    DataType("sleep", "sleep", "sleep.interval.end_time", TimeKind.PHYSICAL, SLEEP),
    _daily(
        "daily-sleep-temperature-derivations",
        "dailySleepTemperatureDerivations",
        "daily_sleep_temperature_derivations",
        SLEEP,
    ),
    # Nutrition
    _civil("hydration-log", "hydrationLog", "hydration_log", NUTRITION),
    _civil("nutrition-log", "nutritionLog", "nutrition_log", NUTRITION),
]

DATA_TYPES: dict[str, DataType] = {dt.key: dt for dt in _ALL}

# Types pulled when the user doesn't pass --types. ECG and IRN need extra
# sensitive scopes, so they are opt-in.
DEFAULT_TYPES = [k for k, dt in DATA_TYPES.items() if dt.scope not in (ECG, IRN)]

# Session types (sleep, exercise) cap pageSize at 25; everything else at 10000.
SESSION_TYPES = {"sleep", "exercise"}


def resolve(keys: list[str] | None) -> list[DataType]:
    """Map user-supplied keys to DataTypes, defaulting to DEFAULT_TYPES."""
    if not keys:
        keys = DEFAULT_TYPES
    unknown = [k for k in keys if k not in DATA_TYPES]
    if unknown:
        raise ValueError(
            f"Unknown data type(s): {', '.join(unknown)}. "
            "Run `fitbit-pull types` to see the options."
        )
    return [DATA_TYPES[k] for k in keys]


def scopes_for(types: list[DataType]) -> list[str]:
    return sorted({dt.scope for dt in types})
