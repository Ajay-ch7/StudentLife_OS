from datetime import date
from pydantic import BaseModel, ConfigDict, Field


class DSAProblemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    topic: str = Field(..., min_length=1, max_length=100)
    difficulty: str = Field(..., min_length=1, max_length=30)
    attempts: int = Field(default=1, ge=1)
    solved_on: date
    needs_revision: bool = False


class DSAProblemResponse(DSAProblemCreate):
    id: int
    user_id: int

    model_config = ConfigDict(from_attributes=True)


class DSAImport(BaseModel):
    problems: list[DSAProblemCreate] = Field(..., min_length=1, max_length=500)
