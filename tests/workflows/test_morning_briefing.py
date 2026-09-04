from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.main import app
from app.models.calendar_event import CalendarEvent
from app.models.deadline import Deadline
from app.models.student_profile import StudentProfile, User
from app.models.task import Task
from app.services.briefing_service import BriefingService
from app.workflows.morning_briefing import MorningBriefingWorkflowRunner


@pytest.fixture
def briefing_test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(email="student@univ.edu", full_name="Casey Miller")
    session.add(user)
    session.commit()
    session.refresh(user)

    profile = StudentProfile(
        user_id=user.id,
        college="UC Berkeley",
        degree="B.S. Computer Science",
        year=3,
        skills="Python, SQL, Distributed Systems",
        available_study_hours=4.0,
    )
    session.add(profile)

    now = datetime.now(timezone.utc)

    today_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)

    # 1. Today's calendar event
    event = CalendarEvent(
        user_id=user.id,
        title="CS186 Database Systems Lecture",
        starts_at=today_noon,
        ends_at=today_noon + timedelta(hours=1, minutes=30),
    )
    session.add(event)

    # 2. Active tasks
    task = Task(
        user_id=user.id,
        title="Complete Normalization HW",
        status="pending",
        priority="high",
        deadline=now + timedelta(days=2),
    )
    session.add(task)

    # 3. Urgent deadline within 24h
    deadline = Deadline(
        user_id=user.id,
        title="Submit Project 1 Checkpoint",
        due_at=now + timedelta(hours=18),
        is_confirmed=True,
    )
    session.add(deadline)
    session.commit()

    yield session, user
    session.close()


def test_gather_briefing_context(briefing_test_db):
    session, user = briefing_test_db
    context = BriefingService.gather_briefing_context(session, user.id)

    assert context["student_name"] == "Casey Miller"
    assert len(context["tasks"]) >= 1
    assert context["tasks"][0]["title"] == "Complete Normalization HW"
    assert len(context["calendar_events"]) >= 1
    assert len(context["urgent_deadlines"]) >= 1


@pytest.mark.asyncio
async def test_generate_briefing_end_to_end(briefing_test_db):
    session, user = briefing_test_db
    service = BriefingService()

    result = await service.generate_briefing(
        db=session,
        user_id=user.id,
        send_notification=True,
    )
    assert result["status"] == "completed"
    assert "Casey" in result["student_name"]
    assert "briefing" in result
    assert len(result["briefing"]["top_priorities"]) >= 1
    assert result["delivery_status"] == "sent"
    assert isinstance(result["mocked_delivery"], bool)


@pytest.mark.asyncio
async def test_morning_briefing_workflow_runner(briefing_test_db):
    session, user = briefing_test_db
    runner = MorningBriefingWorkflowRunner()

    result = await runner.execute(db=session, user_id=user.id, send_notification=False)
    assert result["status"] == "completed"
    assert len(result["briefing"]["top_priorities"]) >= 1


def test_briefing_api_endpoints():
    client = TestClient(app)

    # 1. Trigger POST /api/v1/workflows/morning-briefing
    resp = client.post(
        "/api/v1/workflows/morning-briefing",
        json={"send_notification": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert "briefing" in body

    # 2. Query GET /api/v1/notifications
    notif_resp = client.get("/api/v1/notifications")
    assert notif_resp.status_code == 200
    notifs = notif_resp.json()
    assert len(notifs) >= 1
    assert any(n["type"] == "morning_briefing_generated" for n in notifs)
