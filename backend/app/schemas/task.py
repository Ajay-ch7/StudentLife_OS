from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


TASK_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
TASK_PRIORITIES = {"low", "medium", "high", "urgent"}


class TaskInput(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    deadline: datetime | None = None
    status: str = "pending"
    priority: str = "medium"
    category: str | None = Field(default=None, max_length=100)
    estimated_effort_hours: int | None = Field(default=None, ge=1, le=1000)
    source: str | None = Field(default=None, max_length=100)
    is_confirmed_deadline: bool = True

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in TASK_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(TASK_STATUSES))}")
        return value

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, value: str) -> str:
        if value not in TASK_PRIORITIES:
            raise ValueError(f"priority must be one of: {', '.join(sorted(TASK_PRIORITIES))}")
        return value


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    deadline: datetime | None = None
    status: str | None = None
    priority: str | None = None
    category: str | None = Field(default=None, max_length=100)
    estimated_effort_hours: int | None = Field(default=None, ge=1, le=1000)
    source: str | None = Field(default=None, max_length=100)
    is_confirmed_deadline: bool | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in TASK_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(TASK_STATUSES))}")
        return value

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, value: str | None) -> str | None:
        if value is not None and value not in TASK_PRIORITIES:
            raise ValueError(f"priority must be one of: {', '.join(sorted(TASK_PRIORITIES))}")
        return value


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    description: str | None = None
    deadline: datetime | None = None
    status: str
    priority: str
    category: str | None = None
    estimated_effort_hours: int | None = None
    source: str | None = None
    is_confirmed_deadline: bool
    is_overdue: bool = False
