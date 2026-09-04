from datetime import datetime

from pydantic import BaseModel, Field


class ApprovalCreate(BaseModel):
    action_type: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1)
    metadata_json: str | None = None
    expires_at: datetime | None = None


class ApprovalAction(BaseModel):
    reason: str | None = Field(default=None, max_length=500)