"""
Tests for low-priority calendar event shifting to free days with Telegram approval gate.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.approval_request import ApprovalRequest
from app.models.calendar_event import CalendarEvent
from app.models.student_profile import User
from app.models.task import Task
from app.services.approval_service import ApprovalService
from app.services.orchestrator import multi_agent_orchestrator
from app.services.scheduling_service import (
    detect_shiftable_low_priority_events,
    find_candidate_free_slots,
    get_management_context_snapshot,
    is_high_priority_event,
    is_low_priority_event,
    normalize_datetime,
)
from app.services.telegram_bot_listener import (
    TelegramBotListener,
    is_schedule_shift_request,
)

TEST_DB_URL = "sqlite://"


@pytest.fixture()
def db():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    user = User(full_name="Shift Test Student", email=f"shift-{uuid.uuid4().hex[:6]}@test.com")
    session.add(user)
    session.commit()
    session.refresh(user)
    yield session, user.id
    session.close()
    Base.metadata.drop_all(engine)


def test_priority_classification(db):
    session, user_id = db
    now = datetime.now(timezone.utc)

    # High priority events
    interview_event = CalendarEvent(
        user_id=user_id,
        title="Technical Interview with Google",
        starts_at=now,
        ends_at=now + timedelta(hours=1),
        event_type="career",
    )
    exam_event = CalendarEvent(
        user_id=user_id,
        title="Midterm Examination - CS301",
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=2),
        event_type="exam",
    )

    # Low priority events
    study_event = CalendarEvent(
        user_id=user_id,
        title="Learning Plan: System Design & Graphs",
        starts_at=now + timedelta(hours=2),
        ends_at=now + timedelta(hours=3),
        event_type="study",
    )
    dsa_practice = CalendarEvent(
        user_id=user_id,
        title="Daily DSA Practice - Dynamic Programming",
        starts_at=now + timedelta(days=2),
        ends_at=now + timedelta(days=2, hours=1),
        event_type="study",
    )

    assert is_high_priority_event(interview_event) is True
    assert is_low_priority_event(interview_event) is False

    assert is_high_priority_event(exam_event) is True
    assert is_low_priority_event(exam_event) is False

    assert is_high_priority_event(study_event) is False
    assert is_low_priority_event(study_event) is True

    assert is_high_priority_event(dsa_practice) is False
    assert is_low_priority_event(dsa_practice) is True


def test_detect_shiftable_events_and_candidate_slots(db):
    session, user_id = db
    now = datetime.now(timezone.utc).replace(microsecond=0)

    # Tomorrow at 10:00 AM: High priority interview
    tomorrow_10am = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0)
    interview = CalendarEvent(
        user_id=user_id,
        title="Infosys Onsite Interview",
        starts_at=tomorrow_10am,
        ends_at=tomorrow_10am + timedelta(hours=2),
        event_type="career",
    )

    # Tomorrow at 11:00 AM: Direct clash with interview
    clashing_study = CalendarEvent(
        user_id=user_id,
        title="DSA Practice - Trees",
        starts_at=tomorrow_10am + timedelta(minutes=30),
        ends_at=tomorrow_10am + timedelta(hours=1, minutes=30),
        event_type="study",
    )

    # Tomorrow at 4:00 PM: Same-day crowding
    same_day_learning = CalendarEvent(
        user_id=user_id,
        title="Learning Plan: Microservices",
        starts_at=tomorrow_10am.replace(hour=16),
        ends_at=tomorrow_10am.replace(hour=17),
        event_type="study",
    )

    session.add_all([interview, clashing_study, same_day_learning])
    session.commit()

    shiftable = detect_shiftable_low_priority_events(session, user_id=user_id, days_ahead=5)
    assert len(shiftable) == 2

    # Verify both have recommended new slots on alternative days
    for item in shiftable:
        assert item["recommended_new_start"] is not None
        assert item["recommended_new_end"] is not None
        rec_date = datetime.fromisoformat(item["recommended_new_start"]).date()
        # Candidate day should NOT be tomorrow (the interview day)
        assert rec_date != tomorrow_10am.date()
        assert item["conflicting_high_priority_event"]["title"] == "Infosys Onsite Interview"


@pytest.mark.asyncio
async def test_telegram_shift_proposal_and_approval_workflow(db):
    session, user_id = db
    now = datetime.now(timezone.utc).replace(microsecond=0)

    # Schedule an interview on day + 2
    interview_day = (now + timedelta(days=2)).replace(hour=14, minute=0, second=0)
    interview = CalendarEvent(
        user_id=user_id,
        title="Frontend Engineer Interview",
        starts_at=interview_day,
        ends_at=interview_day + timedelta(hours=1),
        event_type="career",
    )

    # Low priority study session on the exact same afternoon
    study_plan = CalendarEvent(
        user_id=user_id,
        title="Learning Plan: React 19 Compiler",
        starts_at=interview_day.replace(hour=14, minute=30),
        ends_at=interview_day.replace(hour=15, minute=30),
        event_type="study",
    )
    session.add_all([interview, study_plan])
    session.commit()
    session.refresh(study_plan)

    initial_start = study_plan.starts_at

    listener = TelegramBotListener()

    # 1. Trigger proposal generation
    proposal_text = await listener.generate_schedule_shift_proposal(user_id=user_id, db=session)
    assert "Schedule Optimization — Awaiting Your Approval" in proposal_text
    assert "Learning Plan: React 19 Compiler" in proposal_text
    assert "Reply `/approve" in proposal_text

    # Verify approval request created in DB with status pending
    approval_req = (
        session.query(ApprovalRequest)
        .filter(ApprovalRequest.user_id == user_id, ApprovalRequest.status == "pending")
        .first()
    )
    assert approval_req is not None
    assert approval_req.action_type == "orchestrated_plan"
    meta = json.loads(approval_req.metadata_json)
    assert len(meta["agent_actions"]) == 1
    assert meta["agent_actions"][0]["agent"] == "management"
    assert meta["agent_actions"][0]["action"] == "reschedule_event"

    target_new_start = meta["agent_actions"][0]["parameters"]["new_start"]

    # 2. Approve via orchestrator
    exec_results = await multi_agent_orchestrator.execute_approved_plan(session, user_id, approval_req)
    assert len(exec_results) == 1
    assert exec_results[0]["status"] == "executed"
    assert "Shifted" in exec_results[0]["note"]

    # Refresh DB event and confirm its starts_at moved to the new free day
    session.refresh(study_plan)
    assert study_plan.starts_at != initial_start
    assert normalize_datetime(study_plan.starts_at) == normalize_datetime(datetime.fromisoformat(target_new_start))


@pytest.mark.asyncio
async def test_telegram_rejection_leaves_calendar_untouched(db):
    session, user_id = db
    now = datetime.now(timezone.utc).replace(microsecond=0)

    interview_day = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0)
    interview = CalendarEvent(
        user_id=user_id,
        title="Final Round Interview",
        starts_at=interview_day,
        ends_at=interview_day + timedelta(hours=1),
        event_type="career",
    )
    study = CalendarEvent(
        user_id=user_id,
        title="DSA Review - Graphs",
        starts_at=interview_day,
        ends_at=interview_day + timedelta(hours=1),
        event_type="study",
    )
    session.add_all([interview, study])
    session.commit()
    session.refresh(study)

    orig_start = study.starts_at

    listener = TelegramBotListener()
    await listener.generate_schedule_shift_proposal(user_id=user_id, db=session)

    approval_req = (
        session.query(ApprovalRequest)
        .filter(ApprovalRequest.user_id == user_id, ApprovalRequest.status == "pending")
        .first()
    )
    assert approval_req is not None

    # Reject the request
    reject_msg = await listener.handle_command(f"/reject {approval_req.id}", user_id=user_id, db=session)
    assert "rejected" in reject_msg
    assert "No calendar or task changes were made" in reject_msg

    session.refresh(approval_req)
    assert approval_req.status == "rejected"

    # Verify calendar event remained exactly at original time
    session.refresh(study)
    assert study.starts_at == orig_start


def test_natural_language_intent_matching():
    assert is_schedule_shift_request("/optimize") is True
    assert is_schedule_shift_request("/reschedule") is True
    assert is_schedule_shift_request("can the low priority things like learning plans etc in calender to be shifted to other free days so that it doesnt miss the high priority tasks") is True
    assert is_schedule_shift_request("shift low priority study sessions to free days") is True
    assert is_schedule_shift_request("reschedule my learning plan to avoid interview clash") is True
    assert is_schedule_shift_request("what is the weather today?") is False
