from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Rider(InputModel):
    ftp: float = Field(default=238, ge=50, le=1000)
    rider_weight_lb: float = Field(default=184.8, ge=50, le=500)
    bike_weight_lb: float = Field(default=20, ge=5, le=150)
    surface: Literal["road", "gravel"] = "gravel"
    position: Literal["upright", "hoods", "drops", "aero"] = "hoods"

    @property
    def mass_kg(self) -> float:
        return (self.rider_weight_lb + self.bike_weight_lb) * 0.45359237


class IntervalSet(InputModel):
    count: int = Field(default=3, ge=1, le=30)
    duration_seconds: float = Field(default=600, ge=10, le=7200)
    power_low: int = Field(default=210, ge=1, le=2000)
    power_high: int = Field(default=230, ge=1, le=2000)
    recovery_seconds: float = Field(default=300, ge=0, le=7200)
    after_seconds: float = Field(default=0, ge=0, le=86400)
    last_after_seconds: float = Field(default=0, ge=0, le=86400)

    @model_validator(mode="after")
    def ordered_power(self):
        if self.power_low > self.power_high:
            raise ValueError("Interval power_low must not exceed power_high.")
        return self


class WorkoutSpec(InputModel):
    duration_min_seconds: float = Field(default=9000, ge=60, le=86400)
    duration_max_seconds: float = Field(default=9900, ge=60, le=86400)
    endurance_low: float = Field(default=60, gt=0, le=2000)
    endurance_high: float = Field(default=72, gt=0, le=2000)
    endurance_unit: Literal["percent", "watts"] = "percent"
    route_mode: Literal["truncate", "out-and-back"] = "truncate"
    grade_tolerance: float = Field(default=0.015, ge=0.002, le=0.1)
    intervals: list[IntervalSet] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def valid_ranges(self):
        if self.duration_min_seconds > self.duration_max_seconds:
            raise ValueError("Minimum duration must not exceed maximum duration.")
        if self.endurance_low > self.endurance_high:
            raise ValueError("Endurance low must not exceed high.")
        if self.endurance_unit == "percent" and self.endurance_high > 200:
            raise ValueError("Endurance percent must not exceed 200.")
        if sum(s.count for s in self.intervals) > 50:
            raise ValueError("At most 50 intervals may be requested.")
        return self

    def endurance_watts(self, rider: Rider) -> tuple[int, int]:
        scale = rider.ftp / 100 if self.endurance_unit == "percent" else 1
        return max(1, round(self.endurance_low * scale)), max(1, round(self.endurance_high * scale))


@dataclass
class Point:
    lat: float
    lon: float
    elevation: float
    distance: float = 0
    grade: float = 0


@dataclass
class Step:
    start: int
    end: int
    kind: str
    low: int
    high: int
    label: str
    requested_seconds: float = 0
    partial: bool = False

    @property
    def power(self) -> float:
        return (self.low + self.high) / 2


@dataclass
class Cue:
    index: int
    text: str
    kind: str = "generic"


@dataclass
class Plan:
    points: list[Point]
    steps: list[Step]
    times: list[float]
    powers: list[float]
    warnings: list[str] = field(default_factory=list)
    cues: list[Cue] = field(default_factory=list)
    turnaround: int | None = None

    @property
    def duration(self) -> float:
        return self.times[-1]

    @property
    def average_power(self) -> float:
        return sum(p * (b - a) for p, a, b in zip(self.powers, self.times, self.times[1:])) / self.duration
