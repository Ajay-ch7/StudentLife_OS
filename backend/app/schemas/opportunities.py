from pydantic import BaseModel, Field


class OpportunityCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    company: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    required_skills: list[str] = Field(default_factory=list)
    source: str = Field(default="manual", max_length=100)
    url: str | None = None


class ApplicationCreate(BaseModel):
    opportunity_id: int
    notes: str | None = None
