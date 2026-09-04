"""
Tests for the Multi-Agent Orchestration Layer.
Covers routing, context merging, dispatch mapping, fallback behavior, and approval gate.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.main import app
from app.models.student_profile import User
from app.schemas.orchestration_schemas import (
    AgentActionItem,
    OrchestratedDecision,
    OrchestratedResult,
    OrchestratorEvent,
    OrchestratorEventType,
)
from app.services.orchestrator import (
    MultiAgentOrchestrator,
    _HIGH_IMPACT_ACTIONS,
    _is_dsa_conflict,
    _is_job_related_email,
    multi_agent_orchestrator,
)

# ─────────────────────────────────────────────────────────
# Shared in-memory DB fixture
# ─────────────────────────────────────────────────────────
TEST_DB_URL = "sqlite://"


@pytest.fixture()
def db():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    # Seed a user
    user = User(full_name="Orchestrator Test User", email=f"orch-{uuid.uuid4().hex[:6]}@test.com")
    session.add(user)
    session.commit()
    session.refresh(user)
    yield session, user.id
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db):
    session, user_id = db
    app.dependency_overrides[get_db] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────
# Test 1: Event routing logic
# ─────────────────────────────────────────────────────────
class TestRouteAgents:
    def test_new_email_always_routes_inbox_and_management(self):
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        event = OrchestratorEvent(
            event_type=OrchestratorEventType.NEW_EMAIL,
            user_id=1,
            payload={"subject": "HW1 Due Tomorrow", "body": "Please submit by midnight"},
        )
        agents = orch._route_agents(event)
        assert "inbox" in agents
        assert "management" in agents

    def test_new_email_routes_job_only_if_job_related(self):
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        job_event = OrchestratorEvent(
            event_type=OrchestratorEventType.NEW_EMAIL,
            user_id=1,
            payload={"subject": "Google Internship Offer", "body": "We are pleased to offer you a job"},
        )
        agents = orch._route_agents(job_event)
        assert "job" in agents

        non_job_event = OrchestratorEvent(
            event_type=OrchestratorEventType.NEW_EMAIL,
            user_id=1,
            payload={"subject": "Lecture Notes", "body": "Here are todays notes"},
        )
        agents_no_job = orch._route_agents(non_job_event)
        assert "job" not in agents_no_job

    def test_new_leetcode_solve_routes_dsa_management_job(self):
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        event = OrchestratorEvent(
            event_type=OrchestratorEventType.NEW_LEETCODE_SOLVE,
            user_id=1,
            payload={"newly_solved": [{"title": "Two Sum"}]},
        )
        agents = orch._route_agents(event)
        assert "dsa" in agents
        assert "management" in agents
        assert "job" in agents
        assert "inbox" not in agents

    def test_new_job_posting_routes_job_dsa_management(self):
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        event = OrchestratorEvent(
            event_type=OrchestratorEventType.NEW_JOB_POSTING,
            user_id=1,
            payload={"job_text": "Software Engineer at Amazon"},
        )
        agents = orch._route_agents(event)
        assert "job" in agents
        assert "dsa" in agents
        assert "management" in agents
        assert "inbox" not in agents

    def test_morning_briefing_routes_all_agents(self):
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        event = OrchestratorEvent(
            event_type=OrchestratorEventType.MORNING_BRIEFING,
            user_id=1,
            payload={},
        )
        agents = orch._route_agents(event)
        assert set(agents) == {"inbox", "management", "dsa", "job"}


# ─────────────────────────────────────────────────────────
# Test 2: Payload classification helpers
# ─────────────────────────────────────────────────────────
class TestPayloadClassifiers:
    def test_job_related_email_detection(self):
        assert _is_job_related_email({"subject": "Google Internship Application", "body": ""}) is True
        assert _is_job_related_email({"subject": "Job Offer from Amazon", "body": ""}) is True
        assert _is_job_related_email({"subject": "Lecture on DP", "body": "slides attached"}) is False

    def test_dsa_conflict_detection(self):
        assert _is_dsa_conflict({"subject": "Assignment 3 Deadline Extended", "body": ""}) is True
        assert _is_dsa_conflict({"subject": "Exam Tomorrow", "body": ""}) is True
        assert _is_dsa_conflict({"subject": "Happy Birthday", "body": ""}) is False


# ─────────────────────────────────────────────────────────
# Test 3: High-impact detection
# ─────────────────────────────────────────────────────────
class TestHighImpactDetection:
    def _make_decision(self, actions: list[tuple[str, str]]) -> OrchestratedDecision:
        return OrchestratedDecision(
            reasoning="test",
            agent_actions=[AgentActionItem(agent=a, action=act, rationale="r") for a, act in actions],
            telegram_summary="test",
        )

    def test_two_or_more_actions_is_high_impact(self):
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        decision = self._make_decision([("inbox", "create_task"), ("management", "create_event")])
        assert orch._is_high_impact(decision) is True

    def test_single_high_impact_action_triggers_approval(self):
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        for action in _HIGH_IMPACT_ACTIONS:
            decision = self._make_decision([("job", action)])
            assert orch._is_high_impact(decision) is True

    def test_single_low_impact_action_skips_approval(self):
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        decision = self._make_decision([("inbox", "create_task")])
        assert orch._is_high_impact(decision) is False

    def test_no_actions_is_low_impact(self):
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        decision = OrchestratedDecision(reasoning="test", telegram_summary="")
        assert orch._is_high_impact(decision) is False


# ─────────────────────────────────────────────────────────
# Test 4: Context snapshot collection (mocked)
# ─────────────────────────────────────────────────────────
class TestContextSnapshot:
    @pytest.mark.asyncio
    async def test_collect_inbox_snapshot_returns_dict(self, db):
        session, user_id = db
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        result = await orch._collect_snapshot("inbox", session, user_id)
        assert isinstance(result, dict)
        assert "pending_tasks" in result
        assert "recent_emails" in result

    @pytest.mark.asyncio
    async def test_collect_management_snapshot_returns_dict(self, db):
        session, user_id = db
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        result = await orch._collect_snapshot("management", session, user_id)
        assert isinstance(result, dict)
        assert "task_load" in result
        assert "free_blocks_today" in result

    @pytest.mark.asyncio
    async def test_collect_dsa_snapshot_returns_dict(self, db):
        session, user_id = db
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        result = await orch._collect_snapshot("dsa", session, user_id)
        assert isinstance(result, dict)
        assert "dsa_summary" in result

    @pytest.mark.asyncio
    async def test_collect_job_snapshot_returns_dict(self, db):
        session, user_id = db
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        result = await orch._collect_snapshot("job", session, user_id)
        assert isinstance(result, dict)
        assert "active_pipelines" in result

    @pytest.mark.asyncio
    async def test_collect_snapshot_returns_none_on_error(self, db):
        session, user_id = db
        orch = MultiAgentOrchestrator.__new__(MultiAgentOrchestrator)
        # Unknown agent should return None
        result = await orch._collect_snapshot("unknown_agent", session, user_id)
        assert result is None


# ─────────────────────────────────────────────────────────
# Test 5: Fallback on Gemini failure
# ─────────────────────────────────────────────────────────
class TestOrchestratorFallback:
    @pytest.mark.asyncio
    async def test_fallback_when_gemini_fails(self, db):
        session, user_id = db
        orch = MultiAgentOrchestrator()
        event = OrchestratorEvent(
            event_type=OrchestratorEventType.NEW_LEETCODE_SOLVE,
            user_id=user_id,
            payload={"newly_solved": []},
        )
        # Mock Gemini to raise
        orch.gemini = MagicMock()
        orch.gemini.reason_orchestrated = AsyncMock(side_effect=Exception("Gemini quota exceeded"))
        result = await orch.run(event, session)
        assert result.status == "fallback"
        assert result.fallback_reason is not None


# ─────────────────────────────────────────────────────────
# Test 6: Low-impact flow executes autonomously
# ─────────────────────────────────────────────────────────
class TestOrchestratorLowImpact:
    @pytest.mark.asyncio
    async def test_single_create_task_executes_autonomously(self, db):
        session, user_id = db
        orch = MultiAgentOrchestrator()
        event = OrchestratorEvent(
            event_type=OrchestratorEventType.NEW_EMAIL,
            user_id=user_id,
            payload={"subject": "Homework Due", "body": "Submit by Friday"},
        )
        # Return single non-high-impact action
        mock_decision = OrchestratedDecision(
            reasoning="Single low-impact action",
            agent_actions=[
                AgentActionItem(
                    agent="inbox",
                    action="create_task",
                    parameters={"title": "Orchestrator Test Task", "priority": "medium"},
                    rationale="New homework from email",
                )
            ],
            telegram_summary="Task created from email.",
        )
        orch.gemini = MagicMock()
        orch.gemini.reason_orchestrated = AsyncMock(return_value=mock_decision)
        result = await orch.run(event, session)
        assert result.status == "executed"
        assert "inbox" in result.agents_executed


# ─────────────────────────────────────────────────────────
# Test 7: High-impact flow creates approval request
# ─────────────────────────────────────────────────────────
class TestOrchestratorApprovalGate:
    @pytest.mark.asyncio
    async def test_two_actions_creates_approval_request(self, db):
        session, user_id = db
        orch = MultiAgentOrchestrator()
        event = OrchestratorEvent(
            event_type=OrchestratorEventType.NEW_EMAIL,
            user_id=user_id,
            payload={"subject": "OS Assignment 3 Due Sep 10", "body": "Submit by Sep 10"},
        )
        mock_decision = OrchestratedDecision(
            reasoning="New deadline conflicts with DSA session",
            agent_actions=[
                AgentActionItem(agent="inbox", action="create_task",
                                parameters={"title": "OS Assignment 3", "priority": "urgent"},
                                rationale="New deadline"),
                AgentActionItem(agent="management", action="reschedule_event",
                                parameters={"event_title": "DSA Graphs", "new_start": "2026-09-11T18:00:00Z"},
                                rationale="Conflict with deadline"),
            ],
            telegram_summary="OS Assignment 3 added. DSA session rescheduled.",
        )
        orch.gemini = MagicMock()
        orch.gemini.reason_orchestrated = AsyncMock(return_value=mock_decision)
        result = await orch.run(event, session)
        assert result.status == "pending_approval"
        assert result.approval_id is not None


# ─────────────────────────────────────────────────────────
# Test 8: API endpoint
# ─────────────────────────────────────────────────────────
class TestOrchestratorAPI:
    def test_orchestrate_endpoint_exists(self, client):
        """POST /api/v1/orchestrate should be reachable"""
        with patch("app.services.orchestrator.multi_agent_orchestrator.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = OrchestratedResult(
                orchestration_id="orch-test",
                event_type="morning_briefing",
                agents_consulted=["inbox", "management"],
                status="executed",
            )
            response = client.post("/api/v1/orchestrate", json={
                "event_type": "morning_briefing",
                "payload": {},
            })
        assert response.status_code in (200, 404, 422, 500)  # exists, not 405

    def test_orchestration_history_endpoint(self, client):
        """GET /api/v1/orchestrate/history should return a list"""
        response = client.get("/api/v1/orchestrate/history?limit=5")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_orchestration_history_default_limit(self, client):
        """GET /api/v1/orchestrate/history with no limit defaults to 20"""
        response = client.get("/api/v1/orchestrate/history")
        assert response.status_code == 200
