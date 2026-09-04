from datetime import datetime
from pydantic import BaseModel, Field


class FocusSessionCreate(BaseModel):
    topic: str = Field(..., min_length=1, max_length=255)
    planned_start: datetime
    planned_end: datetime
    task_id: int | None = None


class FocusSessionEnd(BaseModel):
    actual_end: datetime | None = None
