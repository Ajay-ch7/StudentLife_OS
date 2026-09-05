import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.core.config import get_settings
import uuid
from app.db.database import Base, get_db, init_db, SessionLocal
from sqlalchemy.orm import Session
from app.main import app
from app.models.email_message import EmailMessage
from app.models.student_profile import User
from app.services.featherless_service import FeatherlessService
from app.services.decision_context_service import DecisionContextService
from app.services.telegram_bot_listener import TelegramBotListener, is_explanation_request


@pytest.fixture
def db_session():
    init_db()
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def mock_featherless_response():
    return {
        "choices": [
            {
                "message": {
                    "content": (
                        "1. Decision made: Set priority to HIGH and scheduled deadline reminder.\n"
                        "2. Why it was made: The email from Prof. Smith emphasized strict 0-late-submission policy.\n"
                        "3. Factors/constraints: The assignment accounts for 25% of the total course grade."
                    )
                }
            }
        ]
    }


def test_is_explanation_request_detection():
    # Positive triggers
    assert is_explanation_request("why") is True
    assert is_explanation_request("Why?") is True
    assert is_explanation_request("/why") is True
    assert is_explanation_request("/explain") is True
    assert is_explanation_request("why did you mark this priority as high?") is True
    assert is_explanation_request("Why was that deadline changed to Oct 15?") is True
    assert is_explanation_request("can you elaborate on that decision?") is True
    assert is_explanation_request("explain your reasoning for this schedule") is True
    assert is_explanation_request("what was the reason for moving my meeting?") is True
    assert is_explanation_request("explain recent decision") is True

    # Negative triggers (regular queries or commands)
    assert is_explanation_request("add study session at 5pm") is False
    assert is_explanation_request("what are my pending tasks for today?") is False
    assert is_explanation_request("sync google calendar") is False
    assert is_explanation_request("check my emails for any assignments") is False
    assert is_explanation_request("submit project 1") is False


def test_featherless_service_prompt_construction():
    service = FeatherlessService()
    ctx = {
        "decision_summary": "Created task 'CS 101 Final Project'",
        "action_taken": "Priority set to URGENT",
        "brief_reason": "Final project worth 40% of grade with imminent deadline.",
    }
    prompt = service._build_explanation_prompt(ctx, user_query="Why is this urgent?")

    assert "DECISION CONTEXT (Ground Truth):" in prompt
    assert "Created task 'CS 101 Final Project'" in prompt
    assert "What decision was made" in prompt
    assert "Why it was made" in prompt
    assert "What factors/constraints influenced it" in prompt
    assert "Why is this urgent?" in prompt


@pytest.mark.asyncio
async def test_featherless_service_explain_decision(mock_featherless_response):
    service = FeatherlessService()
    ctx = {
        "decision_id": 1,
        "brief_reason": "Urgent deadline approaching",
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_featherless_response

    settings = get_settings()
    with patch.object(settings, "featherless_api_key", "test-key"), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        result = await service.explain_decision(ctx, user_query="Why did you do that?")

        assert mock_post.called
        call_kwargs = mock_post.call_args.kwargs
        assert "Authorization" in call_kwargs["headers"]
        assert call_kwargs["headers"]["Authorization"].startswith("Bearer ")
        assert call_kwargs["json"]["model"] == service.model
        assert "Decision made:" in result
        assert "Prof. Smith" in result


def get_or_create_user(db: Session, email: str, name: str) -> User:
    u = db.query(User).filter(User.email == email).first()
    if not u:
        u = User(email=email, full_name=name)
        db.add(u)
        db.commit()
        db.refresh(u)
    return u


def test_decision_context_service_resolution(db_session):
    # Create or fetch test user
    user = get_or_create_user(db_session, "student_exp@college.edu", "Explanation Student")

    # Create email decision record with brief reason
    email_rec = EmailMessage(
        user_id=user.id,
        gmail_id=f"gmail_exp_{uuid.uuid4().hex[:12]}",
        sender="prof.adams@university.edu",
        subject="Midterm Exam Rescheduled",
        snippet="The midterm is moved to Friday due to auditorium conflict.",
        processing_status="processed",
        priority="high",
        requires_action=True,
        reasoning="Midterm date moved by professor; conflict with auditorium resolved.",
    )
    db_session.add(email_rec)
    db_session.commit()

    # Query latest decision
    ctx = DecisionContextService.get_relevant_decision(user.id, db_session, query="Why was the midterm moved?")
    assert ctx is not None
    assert ctx["decision_type"] == "email_to_action"
    assert "Midterm Exam Rescheduled" in ctx["decision_summary"]
    assert "Midterm date moved" in ctx["brief_reason"]


@pytest.mark.asyncio
async def test_telegram_listener_routes_explanation_to_featherless_without_gemini(db_session, mock_featherless_response):
    listener = TelegramBotListener()

    user = get_or_create_user(db_session, "student_tg@college.edu", "Telegram Student")

    # Add email decision
    email_rec = EmailMessage(
        user_id=user.id,
        gmail_id=f"gmail_tg_{uuid.uuid4().hex[:12]}",
        sender="ta@university.edu",
        subject="Lab 4 Deadline Extension",
        snippet="Lab 4 deadline extended to Sunday midnight.",
        processing_status="processed",
        priority="medium",
        requires_action=True,
        reasoning="TA granted a 48-hour extension due to cluster downtime.",
    )
    db_session.add(email_rec)
    db_session.commit()

    # Mock Featherless explanation
    with patch.object(listener.featherless, "explain_decision", new_callable=AsyncMock) as mock_featherless_explain, \
         patch.object(listener.gemini.client, "generate_json", new_callable=AsyncMock) as mock_gemini_call:

        mock_featherless_explain.return_value = "Decision: Updated deadline to Sunday. Reason: Cluster downtime."

        reply = await listener.handle_natural_language(
            "Why did you change the Lab 4 deadline?",
            user_id=user.id,
            db=db_session,
        )

        # Verify Featherless AI was called
        assert mock_featherless_explain.called
        assert "Decision Explanation (via Featherless AI)" in reply
        assert "Cluster downtime" in reply

        # Verify Gemini was NEVER called for the explanation!
        assert not mock_gemini_call.called


def test_api_explain_endpoint(db_session, mock_featherless_response):
    client = TestClient(app)

    user = get_or_create_user(db_session, "api_student@college.edu", "API Student")

    email_rec = EmailMessage(
        user_id=user.id,
        gmail_id=f"gmail_api_{uuid.uuid4().hex[:12]}",
        sender="dean@college.edu",
        subject="Scholarship Application Deadline",
        snippet="Apply by next Monday.",
        processing_status="processed",
        priority="urgent",
        requires_action=True,
        reasoning="Critical funding opportunity for student with strict cutoff.",
    )
    db_session.add(email_rec)
    db_session.commit()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_featherless_response

    settings = get_settings()
    with patch.object(settings, "featherless_api_key", "test-key"), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        # Override user auth dependency
        from app.api.v1.dependencies import get_current_user_id
        from app.db.database import get_db

        app.dependency_overrides[get_current_user_id] = lambda: user.id
        app.dependency_overrides[get_db] = lambda: db_session

        try:
            res = client.post(
                "/api/v1/agent/explain",
                json={"query": "Why was the scholarship marked urgent?"},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["provider"] == "featherless_ai"
            assert data["model"] == "Qwen/Qwen2.5-1.5B-Instruct"
            assert "Decision made:" in data["explanation"]
            assert data["brief_reason"] == "Critical funding opportunity for student with strict cutoff."
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_normal_response_keeps_brief_reason_without_featherless(db_session):
    """
    Verify that standard conversational queries or actions return brief reasons
    and NEVER trigger Featherless AI calls.
    """
    listener = TelegramBotListener()

    user = get_or_create_user(db_session, "normal_tg@college.edu", "Normal Student")

    mock_gemini_json = (
        '{"tool_name": "create_task", "parameters": {"title": "Math HW 3", "priority": "medium", "reason": "Weekly practice problem set"}, "conversational_reply": "Task created with medium priority."}'
    )

    with patch.object(listener.featherless, "explain_decision", new_callable=AsyncMock) as mock_featherless_explain, \
         patch.object(listener.gemini.client, "generate_json", new_callable=AsyncMock) as mock_gemini_call:

        mock_gemini_call.return_value = mock_gemini_json

        reply = await listener.handle_natural_language(
            "Add a task to finish Math HW 3",
            user_id=user.id,
            db=db_session,
        )

        # Verify Gemini parsed the action
        assert mock_gemini_call.called

        # Verify Featherless was NOT called (no unnecessary API calls)
        assert not mock_featherless_explain.called

        # Verify the reply is concise and does NOT include elaborated explanation
        assert "Task created in database:" in reply
        assert "Decision Explanation (via Featherless AI)" not in reply

