from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CalendarEventInput(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    starts_at: datetime
    ends_at: datetime
    event_type: str = Field(default="event", min_length=1, max_length=50)
    location: str | None = Field(default=None, max_length=255)
    task_id: int | None = Field(default=None, ge=1)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value

    @model_validator(mode="after")
    def end_must_follow_start(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class CalendarEventUpdate(CalendarEventInput):
    pass


class CalendarEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    task_id: int | None = None
    title: str
    description: str | None = None
    starts_at: datetime
    ends_at: datetime
    event_type: str
    location: str | None = None


class AvailabilityWindow(BaseModel):
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def end_must_follow_start(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class AvailabilityRequest(BaseModel):
    windows: list[AvailabilityWindow] = Field(min_length=1, max_length=50)
    duration_minutes: int = Field(default=60, ge=15, le=480)
    task_id: int | None = Field(default=None, ge=1)


class AvailableBlock(BaseModel):
    starts_at: datetime
    ends_at: datetime


class ConflictResponse(BaseModel):
    has_conflict: bool
    reasons: list[str]


class RescheduleInput(BaseModel):
    event_id: int = Field(ge=1)
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def end_must_follow_start(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self
