from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.main import app
from app.models.student_profile import StudentProfile, User
from app.models.task import Task
from openclaw.workflows.briefing_workflow import MorningBriefingWorkflow
from openclaw.workflows.inbox_workflow import InboxProcessingWorkflow
from openclaw.workflows.opportunity_workflow import OpportunityEvaluationWorkflow


@pytest.fixture
def workflow_test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(email="alex@school.edu", full_name="Alex River")
    session.add(user)
    session.commit()
    session.refresh(user)

    profile = StudentProfile(
        user_id=user.id,
        college="Berkeley",
        degree="B.S. Computer Science",
        year=3,
        skills="Python, SQL, FastAPI, Docker",
        target_roles="Backend Engineer",
        available_study_hours=4.0,
    )
    session.add(profile)
    session.commit()

    yield session, user
    session.close()


@pytest.mark.asyncio
async def test_inbox_processing_workflow(workflow_test_db):
    session, user = workflow_test_db
    workflow = InboxProcessingWorkflow()

    result = await workflow.run(
        user_id=user.id,
        db=session,
        payload={"content": "Please submit Assignment 3 on Canvas by Friday at 11:59 PM."},
    )
    assert result["status"] == "completed"
    assert result["tasks_extracted"] >= 1
    assert len(result["tasks_created"]) >= 1

    # Verify task was persisted into SQLite
    tasks = session.query(Task).filter(Task.user_id == user.id).all()
    assert len(tasks) >= 1


@pytest.mark.asyncio
async def test_morning_briefing_workflow(workflow_test_db):
    session, user = workflow_test_db
    workflow = MorningBriefingWorkflow()

    result = await workflow.run(user_id=user.id, db=session)
    assert result["status"] == "completed"
    briefing = result["briefing"]
    assert "greeting" in briefing
    assert len(briefing["top_priorities"]) >= 1


@pytest.mark.asyncio
async def test_opportunity_evaluation_workflow(workflow_test_db):
    session, user = workflow_test_db
    workflow = OpportunityEvaluationWorkflow()

    result = await workflow.run(
        user_id=user.id,
        db=session,
        payload={"query": "backend"},
    )
    assert result["status"] == "completed"
    assert "analysis" in result
    assert result["analysis"]["match_score"] >= 0


def test_agent_api_endpoints():
    client = TestClient(app)

    # 1. GET /api/v1/agent/status
    status_resp = client.get("/api/v1/agent/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "ready"
    assert "inbox_processing" in status_resp.json()["available_workflows"]

    # 2. POST /api/v1/agent/run-workflow
    run_resp = client.post(
        "/api/v1/agent/run-workflow",
        json={
            "workflow_name": "inbox_processing",
            "payload": {"content": "Midterm review session tomorrow at 3 PM."},
        },
    )
    assert run_resp.status_code == 200
    body = run_resp.json()
    assert body["workflow_name"] == "inbox_processing"
    assert body["status"] == "completed"

    # 3. GET /api/v1/agent/history
    hist_resp = client.get("/api/v1/agent/history")
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    assert len(history) >= 1
