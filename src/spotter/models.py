from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Nonnegative = Annotated[float, Field(ge=0)]
Positive = Annotated[float, Field(gt=0)]
Identifier = Annotated[int, Field(gt=0, strict=True)]
WeightUnit = Literal["kg", "lb"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    notes: str | None = None

    @model_validator(mode="after")
    def check_units(self) -> Self:
        for value, unit in (
            ("weight", "weight_unit"),
            ("distance", "distance_unit"),
            ("reported_pace", "pace_unit"),
            ("max_speed", "speed_unit"),
        ):
            if getattr(self, value, None) is not None and getattr(self, unit, None) is None:
                raise ValueError(f"{unit} is required when {value} is supplied")
        return self


class BodyMeasurement(Record):
    measured_at: AwareDatetime | None = None
    weight: Positive | None = None
    weight_unit: WeightUnit | None = None


class Session(Record):
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_interval(self) -> Self:
        if self.start_at is not None and self.end_at is not None and self.end_at < self.start_at:
            raise ValueError("end_at must be at or after start_at")
        return self


class Run(Record):
    workout_id: Identifier | None = None
    distance: Nonnegative | None = None
    distance_unit: Literal["m", "km", "mi"] | None = None
    duration_seconds: Positive | None = None
    duration_kind: Literal["moving", "elapsed"] | None = None
    reported_pace: Positive | None = None
    pace_unit: Literal["sec/km", "sec/mi"] | None = None
    pace_kind: Literal["current", "average", "unknown"] | None = None
    max_speed: Nonnegative | None = None
    speed_unit: Literal["km/h", "mph"] | None = None

    @model_validator(mode="after")
    def check_pace_kind(self) -> Self:
        if self.reported_pace is not None and self.pace_kind is None:
            raise ValueError("pace_kind is required for reported pace; use unknown if unspecified")
        return self


class Exercise(Record):
    name: Annotated[str, Field(min_length=1)] | None = None
    equipment: str | None = None

    @model_validator(mode="after")
    def check_name(self) -> Self:
        if self.name is not None and not self.name.strip():
            raise ValueError("name must contain text")
        return self


class StrengthSet(Record):
    workout_id: Identifier | None = None
    exercise_id: Identifier | None = None
    set_order: Identifier | None = None
    reps: Annotated[int, Field(ge=0, strict=True)] | None = None
    weight: Nonnegative | None = None
    weight_unit: WeightUnit | None = None
    effort_note: str | None = None


MODELS: dict[str, type[Record]] = {
    "body_measurements": BodyMeasurement,
    "sessions": Session,
    "runs": Run,
    "exercises": Exercise,
    "strength_sets": StrengthSet,
}
