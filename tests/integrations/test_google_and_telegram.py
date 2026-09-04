from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.student_profile import User
from app.models.calendar_event import CalendarEvent
from app.models.task import Task
from app.models.approval_request import ApprovalRequest
from app.services.telegram_bot_listener import TelegramBotListener
from app.integrations.google_calendar_adapter import GoogleCalendarAdapter
from app.integrations.gmail_adapter import GmailAdapter
from app.tools.tool_registry import tool_registry


@pytest.fixture
def mock_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(email="test@university.edu", full_name="Test Student")
    session.add(user)
    session.commit()
    session.refresh(user)

    event = CalendarEvent(
        user_id=user.id,
        title="Math Lecture",
        starts_at=datetime.now(timezone.utc),
        ends_at=datetime.now(timezone.utc),
    )
    session.add(event)

    task = Task(
        user_id=user.id,
        title="Study Chemistry",
        status="pending",
        priority="high",
    )
    session.add(task)
    session.commit()

    yield session, user
    session.close()


def test_google_tools_registered():
    schemas = tool_registry.get_schemas()
    tool_names = {s.name for s in schemas}
    assert "sync_google_calendar" in tool_names
    assert "create_google_calendar_event" in tool_names
    assert "list_gmail_messages" in tool_names
    assert "create_email_draft" in tool_names
    assert "send_email_draft" in tool_names


def test_send_email_draft_requires_approval():
    schemas = tool_registry.get_schemas()
    send_tool = next(s for s in schemas if s.name == "send_email_draft")
    assert send_tool.requires_approval is True
    assert send_tool.access_level.value == "external_or_consequential"


def test_google_adapters_graceful_fallback(monkeypatch):
    monkeypatch.setattr("app.integrations.google_calendar_adapter.get_calendar_service", lambda: None)
    monkeypatch.setattr("app.integrations.gmail_adapter.get_gmail_service", lambda: None)
    cal = GoogleCalendarAdapter()
    assert cal.is_connected() is False
    assert cal.list_events() == []

    gmail = GmailAdapter()
    assert gmail.is_connected() is False
    assert len(gmail.list_recent_messages()) >= 1
    draft_res = gmail.create_draft("prof@edu.com", "Test", "Hello")
    assert draft_res["status"] == "success"
    assert draft_res["mocked"] is True


@pytest.mark.asyncio
async def test_telegram_bot_commands(mock_db):
    session, user = mock_db
    listener = TelegramBotListener()

    # Test /help
    help_resp = await listener.handle_command("/help", user_id=user.id, db=session)
    assert "StudentLife OS" in help_resp
    assert "/calendar" in help_resp

    # Test /tasks
    tasks_resp = await listener.handle_command("/tasks", user_id=user.id, db=session)
    assert "Study Chemistry" in tasks_resp

    # Test /drafts (empty)
    drafts_resp = await listener.handle_command("/drafts", user_id=user.id, db=session)
    assert "No pending approvals" in drafts_resp
