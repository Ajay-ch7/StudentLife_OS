from pydantic import BaseModel, ConfigDict, Field


class OpportunityCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    company: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    required_skills: list[str] = Field(default_factory=list)
    source: str = Field(default="manual", max_length=100)
    url: str | None = None


class OpportunityResponse(BaseModel):
    id: int
    user_id: int
    title: str
    company: str
    description: str
    required_skills: str | None = None
    match_score: float | None = None
    source: str = "manual"
    url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ApplicationCreate(BaseModel):
    opportunity_id: int
    notes: str | None = None


class ApplicationResponse(BaseModel):
    id: int
    user_id: int
    opportunity_id: int
    status: str
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)

