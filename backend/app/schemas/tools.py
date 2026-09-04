from datetime import datetime
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class ToolAccessLevel(str, Enum):
    READ_LOCAL = "read_local"
    WRITE_LOCAL = "write_local"
    EXTERNAL_ACTION = "external_action"
    EXTERNAL_OR_CONSEQUENTIAL = "external_or_consequential"



class ToolDefinition(BaseModel):
    name: str = Field(..., description="Unique tool name")
    description: str = Field(..., description="Description of what the tool does")
    access_level: ToolAccessLevel = Field(..., description="Permission/security classification")
    requires_approval: bool = Field(False, description="Whether human approval is required before running")
    parameters: dict[str, Any] = Field(default_factory=dict, description="JSON schema for tool inputs")


class ToolRunRequest(BaseModel):
    tool_name: str = Field(..., description="Name of the registered tool to invoke")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Arguments for the tool")
    workflow_id: str | None = Field(None, description="Optional workflow or trace identifier")
    approved: bool = Field(False, description="Explicit approval flag if required")


class ToolRunResponse(BaseModel):
    tool_name: str
    status: Literal["success", "error", "approval_required"]
    result: Any = None
    error: str | None = None
    action_id: int | None = None


# Specific Tool Input/Output Models
class GetProfileInput(BaseModel):
    pass


class GetTasksInput(BaseModel):
    status: str | None = Field(None, description="Filter by status (e.g. pending, completed)")
    priority: str | None = Field(None, description="Filter by priority (e.g. high, urgent)")
    limit: int = Field(50, ge=1, le=200)


class CreateTaskInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    deadline: datetime | None = None
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    category: str | None = None
    estimated_effort_hours: float | None = None
    source: str | None = "manual"


class UpdateTaskInput(BaseModel):
    task_id: int
    title: str | None = None
    description: str | None = None
    deadline: datetime | None = None
    status: Literal["pending", "in_progress", "completed", "cancelled"] | None = None
    priority: Literal["low", "medium", "high", "urgent"] | None = None
    category: str | None = None


class GetCalendarInput(BaseModel):
    start_date: datetime | None = None
    end_date: datetime | None = None
    limit: int = Field(50, ge=1, le=200)


class CreateCalendarEventInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    starts_at: datetime
    ends_at: datetime
    event_type: str = "event"
    location: str | None = None


class RescheduleEventInput(BaseModel):
    event_id: int
    new_starts_at: datetime
    new_ends_at: datetime
    reason: str | None = None


class GetDeadlinesInput(BaseModel):
    upcoming_only: bool = True
    limit: int = Field(50, ge=1, le=200)


class DetectConflictsInput(BaseModel):
    proposed_starts_at: datetime
    proposed_ends_at: datetime
    exclude_event_id: int | None = None


class SearchOpportunitiesInput(BaseModel):
    query: str
    role_type: str | None = None
    limit: int = Field(10, ge=1, le=50)


class AnalyzeOpportunityToolInput(BaseModel):
    opportunity_text: str = Field(..., min_length=10)


class CheckEligibilityInput(BaseModel):
    min_cgpa: float | None = None
    allowed_degrees: list[str] | None = None
    target_year: int | None = None


class AnalyzeSkillGapInput(BaseModel):
    required_skills: list[str] = Field(..., min_length=1)


class GetDSAProgressInput(BaseModel):
    topic: str | None = None


class GenerateStudyPlanToolInput(BaseModel):
    target_date: datetime | None = None
    focus_topic: str | None = None


class ParseDocumentInput(BaseModel):
    file_path: str = Field(..., description="Relative or absolute path within local data/uploads")


class SearchKnowledgeInput(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(5, ge=1, le=20)


class SendTelegramMessageToolInput(BaseModel):
    text: str = Field(..., min_length=1)
    chat_id: str | None = None


class CreateApprovalRequestToolInput(BaseModel):
    action_type: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    metadata_json: str | None = None


class SyncGoogleCalendarInput(BaseModel):
    days_ahead: int = Field(14, ge=1, le=60, description="How many days ahead to sync")


class CreateGoogleCalendarEventInput(BaseModel):
    title: str = Field(..., min_length=1)
    starts_at: datetime
    ends_at: datetime
    description: str | None = ""
    location: str | None = ""


class ListGmailMessagesInput(BaseModel):
    query: str = Field("is:unread", description="Gmail search query like is:unread or from:professor")
    max_results: int = Field(5, ge=1, le=20)


class CreateEmailDraftInput(BaseModel):
    to: str = Field(..., min_length=3, description="Recipient email address")
    subject: str = Field(..., min_length=1, description="Email subject")
    body: str = Field(..., min_length=1, description="Email body text")
    thread_id: str | None = Field(None, description="Optional threadId to reply to")


class SendEmailDraftInput(BaseModel):
    draft_id: str = Field(..., min_length=1, description="ID of the Gmail draft to send")


class ScanGmailInboxInput(BaseModel):
    query: str = Field("is:unread", description="Gmail search query like is:unread, label:inbox, or subject:assignment")
    max_results: int = Field(10, ge=1, le=30, description="Max emails to scan and process")
    dry_run: bool = Field(False, description="Whether to preview extraction without creating tasks")


class SyncLeetCodeProgressInput(BaseModel):
    username: str | None = Field(None, description="Optional LeetCode username to sync")


