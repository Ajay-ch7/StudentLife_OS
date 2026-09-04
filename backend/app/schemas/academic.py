from datetime import datetime
from pydantic import BaseModel, Field


class AssignmentCreate(BaseModel):
    course_name: str = Field(..., min_length=1, max_length=255)
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    due_at: datetime


class ExamCreate(BaseModel):
    course_name: str = Field(..., min_length=1, max_length=255)
    title: str = Field(..., min_length=1, max_length=255)
    starts_at: datetime
    notes: str | None = None


class StudySessionCreate(BaseModel):
    topic: str = Field(..., min_length=1, max_length=255)
    planned_start: datetime
    planned_end: datetime
    task_id: int | None = None


class StudyPlanCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    target_date: datetime | None = None
    session_ids: list[int] = Field(default_factory=list)
