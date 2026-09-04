"""
End-to-End Orchestrator Test for Conflict Resolution:
Simulates an incoming interview schedule conflicting with a low-priority learning plan.
Verifies that:
1. Conflict is detected between the interview and the low-priority learning plan.
2. Orchestrator alerts the user via Telegram and requests approval (/approve <id>).
3. The proposed shift targets a candidate free day.
4. On approval, the learning plan is shifted to the free day and the interview is booked.
5. On rejection, the calendar remains unchanged.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.student_profile import User
from app.models.calendar_event import CalendarEvent
from app.models.approval_request import ApprovalRequest
from app.models.job_pipeline import ActiveJobPipeline
from app.schemas.orchestration_schemas import (
    OrchestratorEvent,
    OrchestratorEventType,
    OrchestratedDecision,
    AgentActionItem,
)
from app.services.orchestrator import MultiAgentOrchestrator, safe_parse_datetime
from app.services.scheduling_service import (
    check_incoming_event_conflicts,
    normalize_datetime,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(
        full_name="Alex Student",
        email="alex.student@university.edu",
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    yield session, user.id
    session.close()


@pytest.mark.asyncio
async def test_interview_conflicts_with_learning_plan_telegram_approval(db_session):
    """
    Scenario:
    User has a low-priority 'DSA Practice & Learning Plan' scheduled on Thursday from 2:00 PM to 4:00 PM.
    A new email arrives with an Interview scheduled by 'Google' on Thursday from 2:00 PM to 3:00 PM.
    The orchestrator must:
    1. Identify the direct calendar conflict.
    2. Propose shifting the learning plan to a free day.
    3. Require user approval via Telegram (/approve).
    4. Upon approval, execute the shift and add the interview to the calendar.
    """
    session, user_id = db_session
    # Establish base anchor date (e.g. Thursday 2:00 PM UTC)
    thursday_start = normalize_datetime(datetime(2026, 9, 10, 14, 0, 0, tzinfo=timezone.utc))
    thursday_end = thursday_start + timedelta(hours=2)

    # 1. User has an existing learning plan on Thursday 2:00 PM - 4:00 PM
    learning_plan_event = CalendarEvent(
        user_id=user_id,
        title="DSA Trees & Graphs Learning Plan",
        description="Daily 2-hour learning block for LeetCode medium questions",
        starts_at=thursday_start,
        ends_at=thursday_end,
        event_type="academic",
    )
    session.add(learning_plan_event)
    session.commit()
    session.refresh(learning_plan_event)

    # 2. Check direct conflict detection service
    conflicts = check_incoming_event_conflicts(
        db=session,
        user_id=user_id,
        starts_at=thursday_start,
        ends_at=thursday_start + timedelta(hours=1),
        incoming_title="Google Technical Interview",
    )
    assert len(conflicts) == 1
    assert conflicts[0]["event_id"] == learning_plan_event.id
    assert conflicts[0]["is_shiftable"] is True
    assert "recommended_new_start" in conflicts[0]

    rec_start = safe_parse_datetime(conflicts[0]["recommended_new_start"])
    assert rec_start is not None
    # Recommended slot must be on a different date/time than the conflict
    assert rec_start != thursday_start

    # 3. Simulate Orchestrator receiving the Interview event
    mock_gemini = AsyncMock()
    # Gemini produces the initial interview recognition
    mock_gemini.reason_orchestrated.return_value = OrchestratedDecision(
        reasoning="Incoming email confirms Google Technical Interview on 2026-09-10 14:00 UTC. Need to schedule it and update pipeline.",
        telegram_summary="Confirmed Google Interview scheduled for Thursday 2:00 PM.",
        agent_actions=[
            AgentActionItem(
                agent="management",
                action="create_event",
                parameters={
                    "title": "Google Technical Interview",
                    "starts_at": thursday_start.isoformat(),
                    "ends_at": (thursday_start + timedelta(hours=1)).isoformat(),
                    "event_type": "career",
                },
                rationale="Book interview slot in calendar",
            ),
            AgentActionItem(
                agent="job",
                action="update_pipeline",
                parameters={
                    "company": "Google",
                    "role_title": "Software Engineer Intern",
                    "status": "interview_scheduled",
                    "date": thursday_start.isoformat(),
                },
                rationale="Advance Google pipeline to interview_scheduled",
            ),
        ],
    )

    orchestrator = MultiAgentOrchestrator(gemini_service=mock_gemini)

    event_payload = {
        "subject": "Interview Confirmation - Google SWE Intern",
        "body": "Your technical interview is confirmed for September 10, 2026 at 2:00 PM UTC.",
        "company": "Google",
        "starts_at": thursday_start.isoformat(),
        "ends_at": (thursday_start + timedelta(hours=1)).isoformat(),
    }
    orch_event = OrchestratorEvent(
        event_type=OrchestratorEventType.NEW_EMAIL,
        user_id=user_id,
        payload=event_payload,
    )

    with patch("app.integrations.telegram_adapter.TelegramAdapter.send_message", new_callable=AsyncMock) as mock_tg:
        result = await orchestrator.run(orch_event, session)

        # 4. Assert conflict handling
        assert result.status == "pending_approval"
        assert result.approval_id is not None
        assert mock_tg.called

        tg_message = mock_tg.call_args[0][0]
        # Check that user is asked for approval and alerted about the conflict & proposed shift
        assert f"/approve {result.approval_id}" in tg_message
        assert "DSA Trees & Graphs Learning Plan" in tg_message
        assert "Google" in tg_message

        # Verify ApprovalRequest in DB
        approval_req = session.query(ApprovalRequest).filter(ApprovalRequest.id == result.approval_id).first()
        assert approval_req is not None
        assert approval_req.status == "pending"
        assert "reschedule_event" in approval_req.metadata_json

    # 5. User approves the plan (/approve <id>)
    approval_req.status = "approved"
    session.commit()

    execution_log = await orchestrator.execute_approved_plan(session, user_id, approval_req)

    # 6. Verify calendar state after approval:
    # A) The low-priority learning plan was shifted to the free day
    session.refresh(learning_plan_event)
    assert normalize_datetime(learning_plan_event.starts_at) != thursday_start
    assert normalize_datetime(learning_plan_event.starts_at) == rec_start

    # B) The Google interview was booked on Thursday at 2:00 PM
    interview_event = (
        session.query(CalendarEvent)
        .filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.title.ilike("%Google%"),
        )
        .first()
    )
    assert interview_event is not None
    assert normalize_datetime(interview_event.starts_at) == thursday_start
    assert interview_event.event_type == "career"

    # C) Job pipeline was updated
    pipeline = (
        session.query(ActiveJobPipeline)
        .filter(
            ActiveJobPipeline.user_id == user_id,
            ActiveJobPipeline.company.ilike("%Google%"),
        )
        .first()
    )
    assert pipeline is not None
    assert pipeline.sop_status == "interview_scheduled"


@pytest.mark.asyncio
async def test_interview_conflict_rejection_leaves_calendar_untouched(db_session):
    """
    Scenario:
    User rejects the shift proposal (/reject <id>).
    Calendar must remain untouched with the original learning plan preserved.
    """
    session, user_id = db_session
    thursday_start = normalize_datetime(datetime(2026, 9, 10, 14, 0, 0, tzinfo=timezone.utc))
    thursday_end = thursday_start + timedelta(hours=2)

    learning_plan_event = CalendarEvent(
        user_id=user_id,
        title="System Design Study Session",
        description="Low priority reading on distributed systems",
        starts_at=thursday_start,
        ends_at=thursday_end,
        event_type="academic",
    )
    session.add(learning_plan_event)
    session.commit()

    mock_gemini = AsyncMock()
    mock_gemini.reason_orchestrated.return_value = OrchestratedDecision(
        reasoning="Interview clashing with study session.",
        telegram_summary="Interview clashing.",
        agent_actions=[
            AgentActionItem(
                agent="management",
                action="create_event",
                parameters={
                    "title": "Amazon Bar Raiser Interview",
                    "starts_at": thursday_start.isoformat(),
                    "ends_at": (thursday_start + timedelta(hours=1)).isoformat(),
                },
                rationale="Book interview",
            ),
        ],
    )

    orchestrator = MultiAgentOrchestrator(gemini_service=mock_gemini)
    orch_event = OrchestratorEvent(
        event_type=OrchestratorEventType.NEW_EMAIL,
        user_id=user_id,
        payload={
            "subject": "Amazon Interview",
            "starts_at": thursday_start.isoformat(),
            "ends_at": (thursday_start + timedelta(hours=1)).isoformat(),
        },
    )

    with patch("app.integrations.telegram_adapter.TelegramAdapter.send_message", new_callable=AsyncMock):
        result = await orchestrator.run(orch_event, session)

    approval_req = session.query(ApprovalRequest).filter(ApprovalRequest.id == result.approval_id).first()
    approval_req.status = "rejected"
    session.commit()

    # Confirm original event untouched
    session.refresh(learning_plan_event)
    assert normalize_datetime(learning_plan_event.starts_at) == thursday_start
    assert normalize_datetime(learning_plan_event.ends_at) == thursday_end

    # Confirm Amazon event was NOT created
    amazon_event = session.query(CalendarEvent).filter(CalendarEvent.title.ilike("%Amazon%")).first()
    assert amazon_event is None
