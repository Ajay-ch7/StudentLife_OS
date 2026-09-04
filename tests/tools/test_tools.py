from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import DATA_DIR
from app.db.database import Base
from app.main import app
from app.models.activity_log import ActivityLog
from app.models.agent_action import AgentAction
from app.models.calendar_event import CalendarEvent
from app.models.student_profile import StudentProfile, User
from app.models.task import Task
from app.tools.tool_registry import tool_registry


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(email="alex@university.edu", full_name="Alex River")
    session.add(user)
    session.commit()
    session.refresh(user)

    profile = StudentProfile(
        user_id=user.id,
        college="Berkeley",
        degree="B.S. Computer Science",
        year=3,
        cgpa=3.85,
        skills="Python, FastAPI, SQL, Docker",
        target_roles="Backend Engineer, Distributed Systems",
        available_study_hours=4.0,
    )
    session.add(profile)

    task = Task(
        user_id=user.id,
        title="DBMS Assignment 2",
        status="pending",
        priority="high",
        deadline=datetime(2026, 9, 20, 23, 59, tzinfo=timezone.utc),
    )
    session.add(task)

    event = CalendarEvent(
        user_id=user.id,
        title="OS Lecture",
        starts_at=datetime(2026, 9, 10, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 9, 10, 15, 30, tzinfo=timezone.utc),
    )
    session.add(event)
    session.commit()

    yield session, user
    session.close()


def test_tool_registry_schemas():
    schemas = tool_registry.get_schemas()
    assert len(schemas) >= 15
    tool_names = {s.name for s in schemas}
    assert "get_student_profile" in tool_names
    assert "create_task" in tool_names
    assert "reschedule_event" in tool_names
    assert "send_telegram_message" in tool_names
    assert "detect_conflicts" in tool_names

    reschedule_tool = next(s for s in schemas if s.name == "reschedule_event")
    assert reschedule_tool.requires_approval is True


@pytest.mark.asyncio
async def test_execute_get_student_profile(test_db):
    session, user = test_db
    response = await tool_registry.execute_tool(
        name="get_student_profile",
        parameters={},
        user_id=user.id,
        db=session,
    )
    assert response.status == "success"
    assert response.result["full_name"] == "Alex River"
    assert "Python" in response.result["skills"]

    # Verify agent action was logged
    action = session.query(AgentAction).filter(AgentAction.id == response.action_id).first()
    assert action is not None
    assert action.tool_name == "get_student_profile"
    assert action.status == "success"


@pytest.mark.asyncio
async def test_execute_create_and_update_task(test_db):
    session, user = test_db
    create_resp = await tool_registry.execute_tool(
        name="create_task",
        parameters={"title": "Prepare Resume", "priority": "urgent", "category": "career"},
        user_id=user.id,
        db=session,
    )
    assert create_resp.status == "success"
    task_id = create_resp.result["id"]

    update_resp = await tool_registry.execute_tool(
        name="update_task",
        parameters={"task_id": task_id, "status": "completed"},
        user_id=user.id,
        db=session,
    )
    assert update_resp.status == "success"
    assert update_resp.result["status"] == "completed"


@pytest.mark.asyncio
async def test_approval_requirement_enforcement(test_db):
    session, user = test_db
    event = session.query(CalendarEvent).filter(CalendarEvent.user_id == user.id).first()

    # Attempt reschedule without approval -> status approval_required
    resp = await tool_registry.execute_tool(
        name="reschedule_event",
        parameters={
            "event_id": event.id,
            "new_starts_at": "2026-09-10T16:00:00Z",
            "new_ends_at": "2026-09-10T17:30:00Z",
        },
        user_id=user.id,
        db=session,
        approved=False,
    )
    assert resp.status == "approval_required"

    # Attempt with approved=True -> succeeds
    resp_approved = await tool_registry.execute_tool(
        name="reschedule_event",
        parameters={
            "event_id": event.id,
            "new_starts_at": "2026-09-10T16:00:00Z",
            "new_ends_at": "2026-09-10T17:30:00Z",
        },
        user_id=user.id,
        db=session,
        approved=True,
    )
    assert resp_approved.status == "success"


@pytest.mark.asyncio
async def test_parse_document_path_safety(test_db, tmp_path):
    session, user = test_db
    # Attempting to read outside DATA_DIR should be blocked
    outside_file = str(tmp_path / "secret.txt")
    resp = await tool_registry.execute_tool(
        name="parse_document",
        parameters={"file_path": outside_file},
        user_id=user.id,
        db=session,
    )
    assert resp.status == "error"
    assert "Access denied" in resp.error

    # Reading inside DATA_DIR succeeds
    valid_file = DATA_DIR / "uploads" / "sample_syllabus.txt"
    valid_file.write_text("CS301 Distributed Systems Syllabus", encoding="utf-8")
    resp_valid = await tool_registry.execute_tool(
        name="parse_document",
        parameters={"file_path": str(valid_file)},
        user_id=user.id,
        db=session,
    )
    assert resp_valid.status == "success"
    assert resp_valid.result["file_name"] == "sample_syllabus.txt"


@pytest.mark.asyncio
async def test_conflict_detection_tool(test_db):
    session, user = test_db
    # Conflict with existing OS Lecture (14:00 - 15:30)
    conflict_resp = await tool_registry.execute_tool(
        name="detect_conflicts",
        parameters={
            "proposed_starts_at": "2026-09-10T14:30:00Z",
            "proposed_ends_at": "2026-09-10T15:00:00Z",
        },
        user_id=user.id,
        db=session,
    )
    assert conflict_resp.status == "success"
    assert conflict_resp.result["has_conflicts"] is True
    assert conflict_resp.result["conflict_count"] >= 1


@pytest.mark.asyncio
async def test_skill_gap_and_eligibility_tools(test_db):
    session, user = test_db
    gap_resp = await tool_registry.execute_tool(
        name="analyze_skill_gap",
        parameters={"required_skills": ["Python", "FastAPI", "Kubernetes", "Rust"]},
        user_id=user.id,
        db=session,
    )
    assert gap_resp.status == "success"
    assert "Python" in gap_resp.result["matched_skills"]
    assert "Rust" in gap_resp.result["missing_skills"]

    elig_resp = await tool_registry.execute_tool(
        name="check_eligibility",
        parameters={"min_cgpa": 3.5, "target_year": 3},
        user_id=user.id,
        db=session,
    )
    assert elig_resp.status == "success"
    assert elig_resp.result["eligible"] is True


def test_tools_api_endpoints():
    client = TestClient(app)
    # Test GET /api/v1/tools/schema
    schema_resp = client.get("/api/v1/tools/schema")
    assert schema_resp.status_code == 200
    schemas = schema_resp.json()
    assert len(schemas) >= 15

    # Test POST /api/v1/tools/run
    run_resp = client.post(
        "/api/v1/tools/run",
        json={"tool_name": "get_dsa_progress", "parameters": {}},
    )
    assert run_resp.status_code == 200
    body = run_resp.json()
    assert body["status"] == "success"
    assert "topics" in body["result"]
