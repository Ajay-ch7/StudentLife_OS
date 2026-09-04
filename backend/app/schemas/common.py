from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserResponse(APIModel):
    id: int
    email: str
    full_name: str
    telegram_name: str | None = None


class ProfileResponse(APIModel):
    id: int
    user_id: int
    timezone: str | None = None
    college: str | None = None
    degree: str | None = None
    year: int | None = None
    cgpa: float | None = None
    target_roles: str | None = None
    target_companies: str | None = None
    skills: str | None = None
    preferred_locations: str | None = None
    available_study_hours: float | None = None
    preferred_study_times: str | None = None
    notification_preferences: str | None = None


class ProfileInput(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    timezone: str | None = Field(default=None, max_length=64)
    college: str | None = Field(default=None, max_length=255)
    degree: str | None = Field(default=None, max_length=255)
    year: int | None = Field(default=None, ge=1, le=10)
    cgpa: float | None = Field(default=None, ge=0, le=10)
    target_roles: str | None = Field(default=None, max_length=500)
    target_companies: str | None = Field(default=None, max_length=500)
    skills: str | None = Field(default=None, max_length=1000)
    preferred_locations: str | None = Field(default=None, max_length=500)
    available_study_hours: float | None = Field(default=None, ge=0, le=24)
    preferred_study_times: str | None = Field(default=None, max_length=500)
    notification_preferences: str | None = Field(default=None, max_length=1000)


class ProfileEnvelope(APIModel):
    user: UserResponse
    profile: ProfileResponse | None = None


class TaskResponse(APIModel):
    id: int
    title: str
    description: str | None = None
    deadline: datetime | None = None
    status: str
    priority: str
    category: str | None = None
    estimated_effort_hours: float | None = None
    source: str | None = None
    is_confirmed_deadline: bool


class DeadlineResponse(APIModel):
    id: int
    task_id: int | None = None
    title: str
    due_at: datetime
    source: str | None = None
    is_confirmed: bool


class CalendarEventResponse(APIModel):
    id: int
    title: str
    description: str | None = None
    starts_at: datetime
    ends_at: datetime
    event_type: str
    location: str | None = None


class ActivityResponse(APIModel):
    id: int
    activity_type: str
    message: str
    created_at: datetime


class ApprovalResponse(APIModel):
    id: int
    action_type: str
    description: str
    metadata_json: str | None = None
    expires_at: datetime | None = None
    result_json: str | None = None
    status: str
    requested_at: datetime
    resolved_at: datetime | None = None