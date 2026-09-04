from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class ExtractedTaskItem(BaseModel):
    title: str = Field(..., description="Short, actionable title for the task")
    description: str | None = Field(None, description="Detailed task requirements or context")
    deadline: datetime | None = Field(None, description="Detected deadline or due date if present")
    priority: Literal["low", "medium", "high", "urgent"] = Field("medium", description="Suggested priority")
    category: str | None = Field(None, description="Category such as assignment, exam, project, admin, career, dsa")
    estimated_effort_hours: float | None = Field(None, description="Estimated hours needed to complete")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")


class ExtractedDeadlineItem(BaseModel):
    title: str = Field(..., description="Description of the deadline event")
    due_at: datetime = Field(..., description="Precise date/time for the deadline")
    source_context: str | None = Field(None, description="Snippet or context indicating the deadline")
    is_hard_deadline: bool = Field(True, description="Whether this is a strict cutoff or suggested target")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")


class TaskAndDeadlineExtractionResult(BaseModel):
    tasks: list[ExtractedTaskItem] = Field(default_factory=list, description="Extracted tasks")
    deadlines: list[ExtractedDeadlineItem] = Field(default_factory=list, description="Extracted standalone deadlines")
    summary: str = Field(..., description="Brief summary of the analyzed content")


class StudySessionItem(BaseModel):
    subject_or_task: str = Field(..., description="Subject or task name to study")
    duration_minutes: int = Field(..., ge=15, le=360, description="Recommended study duration in minutes")
    target_objective: str = Field(..., description="Specific goal for this study session")
    recommended_time_of_day: Literal["morning", "afternoon", "evening", "night"] = Field("afternoon")
    rationale: str = Field(..., description="Why this session is prioritized")


class StudyPlanResult(BaseModel):
    plan_title: str = Field(..., description="Title of the study plan")
    daily_focus: str = Field(..., description="Main objective for the day")
    sessions: list[StudySessionItem] = Field(default_factory=list, description="List of study blocks")
    total_study_minutes: int = Field(..., description="Total planned study duration")
    advisory_notes: list[str] = Field(default_factory=list, description="Tips, breaks, or cautions")


class OpportunitySkillAnalysis(BaseModel):
    matched_skills: list[str] = Field(default_factory=list, description="Skills present in student profile")
    missing_skills: list[str] = Field(default_factory=list, description="Required skills missing from profile")
    match_score: int = Field(..., ge=0, le=100, description="Fit score from 0 to 100")
    recommendation: Literal["strongly_apply", "apply", "prepare_first", "not_recommended"] = Field("apply")
    summary: str = Field(..., description="Summary analysis of fit")
    action_items: list[str] = Field(default_factory=list, description="Steps needed before or during application")


class MorningBriefingResult(BaseModel):
    greeting: str = Field(..., description="Personalized greeting")
    quote_or_motto: str | None = Field(None, description="Short encouraging message")
    top_priorities: list[str] = Field(..., min_length=1, description="Top 2-4 tasks/goals for today")
    schedule_overview: str = Field(..., description="Overview of the day's timeline and calendar")
    urgent_alerts: list[str] = Field(default_factory=list, description="Upcoming deadlines in next 48h")
    recommended_recovery_action: str | None = Field(None, description="Action if behind schedule or facing conflicts")


class ContentClassificationResult(BaseModel):
    trust_level: Literal["trusted", "untrusted", "suspicious"] = Field("untrusted")
    category: Literal["academic_announcement", "assignment_notice", "internship_opportunity", "personal_message", "spam_or_irrelevant"] = Field("academic_announcement")
    contains_actionable_items: bool = Field(True)
    reasoning: str = Field(...)
