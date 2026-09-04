from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.approval_request import ApprovalRequest
from app.models.calendar_event import CalendarEvent
from app.models.student_profile import StudentProfile, User
from app.models.task import Task
from openclaw.agent.student_life_agent import StudentLifeAgent
from openclaw.config import OpenClawConfig


@pytest.fixture
def agent_test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(email="student@univ.edu", full_name="Jordan Lee")
    session.add(user)
    session.commit()
    session.refresh(user)

    profile = StudentProfile(
        user_id=user.id,
        college="Stanford",
        degree="B.S. Software Engineering",
        year=2,
        cgpa=3.9,
        skills="Python, SQL, Algorithms",
        available_study_hours=3.5,
    )
    session.add(profile)

    task = Task(
        user_id=user.id,
        title="Algorithms Problem Set 1",
        status="pending",
        priority="high",
        deadline=datetime(2026, 9, 18, 23, 59, tzinfo=timezone.utc),
    )
    session.add(task)
    session.commit()

    yield session, user
    session.close()


@pytest.mark.asyncio
async def test_agent_get_student_context(agent_test_db):
    session, user = agent_test_db
    agent = StudentLifeAgent()

    context = await agent.get_student_context(user_id=user.id, db=session)
    assert context["profile"]["full_name"] == "Jordan Lee"
    assert len(context["tasks"]) >= 1
    assert context["tasks"][0]["title"] == "Algorithms Problem Set 1"


@pytest.mark.asyncio
async def test_agent_safe_tool_execution(agent_test_db):
    session, user = agent_test_db
    agent = StudentLifeAgent()

    # Direct allowed tool execution
    resp = await agent.run_tool(
        tool_name="create_task",
        parameters={"title": "Read Chapter 4", "priority": "low"},
        user_id=user.id,
        db=session,
    )
    assert resp["status"] == "success"
    assert resp["result"]["title"] == "Read Chapter 4"


@pytest.mark.asyncio
async def test_agent_approval_gated_tool_handling(agent_test_db):
    session, user = agent_test_db
    agent = StudentLifeAgent()

    event = CalendarEvent(
        user_id=user.id,
        title="Math Workshop",
        starts_at=datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 9, 12, 11, 30, tzinfo=timezone.utc),
    )
    session.add(event)
    session.commit()

    # Agent runs reschedule_event without approval -> creates approval_request record
    resp = await agent.run_tool(
        tool_name="reschedule_event",
        parameters={
            "event_id": event.id,
            "new_starts_at": "2026-09-12T14:00:00Z",
            "new_ends_at": "2026-09-12T15:30:00Z",
        },
        user_id=user.id,
        db=session,
        approved=False,
    )
    assert resp["status"] == "approval_required"

    # Verify approval request was created in DB for user to review
    approvals = session.query(ApprovalRequest).filter(ApprovalRequest.user_id == user.id).all()
    assert len(approvals) >= 1
    assert approvals[0].action_type == "reschedule_event"
