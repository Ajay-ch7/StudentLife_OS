"""
Pydantic schemas for the Multi-Agent Orchestration Layer.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


class OrchestratorEventType(str, Enum):
    NEW_EMAIL = "new_email"
    NEW_LEETCODE_SOLVE = "new_leetcode_solve"
    NEW_JOB_POSTING = "new_job_posting"
    CALENDAR_CONFLICT = "calendar_conflict"
    MANUAL_TASK_CREATE = "manual_task_create"
    MORNING_BRIEFING = "morning_briefing"


@dataclass
class OrchestratorEvent:
    event_type: OrchestratorEventType
    user_id: int
    payload: dict[str, Any]
    workflow_id: str = field(default_factory=lambda: f"orch-{uuid.uuid4().hex[:8]}")


class AgentActionItem(BaseModel):
    agent: Literal["inbox", "management", "dsa", "job"]
    action: str
    parameters: dict[str, Any] = {}
    rationale: str = ""


class OrchestratedDecision(BaseModel):
    reasoning: str
    priority_override: str | None = None
    agent_actions: list[AgentActionItem] = []
    skip_agents: list[str] = []
    skip_reason: str | None = None
    telegram_summary: str = ""


class OrchestratedResult(BaseModel):
    orchestration_id: str
    event_type: str
    agents_consulted: list[str] = []
    agents_executed: list[str] = []
    decision: OrchestratedDecision | None = None
    execution_log: list[dict[str, Any]] = []
    status: str  # "executed" | "pending_approval" | "fallback" | "skipped"
    approval_id: int | None = None
    fallback_reason: str | None = None
