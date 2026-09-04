from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.calendar_event import CalendarEvent
from app.models.deadline import Deadline
from app.models.email_message import EmailMessage
from app.models.student_profile import StudentProfile, User
from app.models.task import Task
from app.schemas.email_workflow_schemas import (
    EmailReasoningDecision,
    ExtractedDeadlineItem,
    ExtractedTaskItem,
    TaskUpdateItem,
)
from openclaw.workflows.email_to_action_workflow import EmailToActionWorkflow


@pytest.fixture
def email_workflow_test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(email="student@univ.edu", full_name="Sam Taylor")
    session.add(user)
    session.commit()
    session.refresh(user)

    profile = StudentProfile(
        user_id=user.id,
        college="Tech University",
        degree="B.S. Computer Science",
        year=3,
        skills="Python, SQL, Algorithms",
        available_study_hours=4.0,
    )
    session.add(profile)

    # Busy Calendar event for conflict detection: Sept 15, 2026, 22:00 to 23:59 UTC
    busy_event = CalendarEvent(
        user_id=user.id,
        title="Late Lab Session",
        starts_at=datetime(2026, 9, 15, 22, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 9, 16, 0, 30, tzinfo=timezone.utc),
    )
    session.add(busy_event)
    session.commit()

    yield session, user
    session.close()


@pytest.mark.asyncio
async def test_email_to_action_end_to_end_new_email(email_workflow_test_db):
    session, user = email_workflow_test_db

    # Mock Telegram adapter to verify proactive message
    mock_telegram = MagicMock()
    mock_telegram.send_message = AsyncMock(return_value=MagicMock(mocked=True))

    workflow = EmailToActionWorkflow(telegram_adapter=mock_telegram)

    # Simulate newly arrived assignment email
    incoming_email = {
        "id": "gmail-msg-101",
        "thread_id": "thread-101",
        "from": "Prof. Alan Turing <prof.turing@univ.edu>",
        "subject": "CS301 Assignment 1 - Distributed Systems",
        "date": "2026-09-05T10:00:00Z",
        "body": "Class, Assignment 1 is officially released. The deadline is September 15, 2026 at 11:59 PM. Please submit your repository link.",
    }

    result = await workflow.run(user_id=user.id, db=session, payload=incoming_email)

    assert result["status"] == "completed"
    assert result["priority"] in ("low", "medium", "high", "urgent")

    # 1. Verify email record in database
    email_rec = session.query(EmailMessage).filter(EmailMessage.gmail_id == "gmail-msg-101").first()
    assert email_rec is not None
    assert email_rec.processing_status == "processed"
    assert email_rec.priority is not None
    assert email_rec.reasoning is not None

    # 2. Verify Task creation in database
    tasks = session.query(Task).filter(Task.user_id == user.id).all()
    assert len(tasks) >= 1
    task = tasks[0]
    assert "Assignment" in task.title or "Distributed" in task.title

    # 3. Verify Deadline creation
    deadlines = session.query(Deadline).filter(Deadline.user_id == user.id).all()
    assert len(deadlines) >= 1

    # 4. Verify Proactive Telegram Notification was sent with required format
    assert mock_telegram.send_message.called
    sent_text = mock_telegram.send_message.call_args.kwargs["text"]
    assert "📩 New email processed" in sent_text
    assert f"Priority: {result['priority'].upper()}" in sent_text
    assert "Deadline:" in sent_text
    assert "Changes made:" in sent_text
    assert "Reason:" in sent_text


@pytest.mark.asyncio
async def test_duplicate_prevention_same_email(email_workflow_test_db):
    session, user = email_workflow_test_db

    mock_telegram = MagicMock()
    mock_telegram.send_message = AsyncMock()

    workflow = EmailToActionWorkflow(telegram_adapter=mock_telegram)

    incoming_email = {
        "id": "gmail-dup-001",
        "from": "admin@univ.edu",
        "subject": "Tuition Payment Reminder",
        "body": "Tuition fees are due next week.",
    }

    # First execution: successfully processed
    res1 = await workflow.run(user_id=user.id, db=session, payload=incoming_email)
    assert res1["status"] == "completed"
    first_call_count = mock_telegram.send_message.call_count

    # Second execution: duplicate detected, must be skipped
    res2 = await workflow.run(user_id=user.id, db=session, payload=incoming_email)
    assert res2["status"] == "skipped"
    assert res2["reason"] == "already_processed"

    # Telegram notification should NOT be re-sent for skipped duplicate
    assert mock_telegram.send_message.call_count == first_call_count


@pytest.mark.asyncio
async def test_smart_task_update_instead_of_duplicate(email_workflow_test_db):
    session, user = email_workflow_test_db

    # Pre-populate an existing pending task
    original_deadline = datetime(2026, 9, 10, 23, 59, tzinfo=timezone.utc)
    existing_task = Task(
        user_id=user.id,
        title="CS302 Database Assignment 2",
        description="Normalization problem set 1-5",
        deadline=original_deadline,
        priority="medium",
        status="pending",
    )
    session.add(existing_task)
    session.commit()
    session.refresh(existing_task)

    session.add(
        Deadline(
            user_id=user.id,
            task_id=existing_task.id,
            title=existing_task.title,
            due_at=original_deadline,
            is_confirmed=True,
        )
    )
    session.commit()

    initial_task_count = session.query(Task).filter(Task.user_id == user.id).count()

    # Mock agent reasoning to simulate detecting a deadline extension for Assignment 2
    new_due_date = datetime(2026, 9, 12, 23, 59, tzinfo=timezone.utc)
    mock_gemini = MagicMock()
    mock_gemini.reason_over_email = AsyncMock(
        return_value=EmailReasoningDecision(
            priority="high",
            requires_action=True,
            summary="Assignment 2 deadline extended by 48 hours.",
            reasoning="The professor granted an extension on the database assignment.",
            deadlines=[
                ExtractedDeadlineItem(
                    title="Assignment 2 Extended Deadline",
                    due_at=new_due_date,
                    source_context="Due Sept 12",
                    is_hard_deadline=True,
                    confidence=0.98,
                )
            ],
            tasks_to_create=[],
            tasks_to_update=[
                TaskUpdateItem(
                    existing_task_id=existing_task.id,
                    matching_title_query="Assignment 2",
                    new_title="CS302 Database Assignment 2 (Extended)",
                    new_deadline=new_due_date,
                    new_priority="high",
                    update_reason="Extended by 48 hours",
                )
            ],
            events_to_create=[],
            detected_conflicts=[],
            recommended_action="update_deadline",
            draft_response_needed=False,
            draft_response=None,
        )
    )

    mock_agent = MagicMock()
    mock_agent.gemini = mock_gemini
    mock_telegram = MagicMock()
    mock_telegram.send_message = AsyncMock()

    workflow = EmailToActionWorkflow(agent=mock_agent, telegram_adapter=mock_telegram)

    extension_email = {
        "id": "gmail-ext-202",
        "from": "prof@univ.edu",
        "subject": "CS302 Assignment 2 Deadline Extension",
        "body": "Class, I am extending the Assignment 2 deadline to September 12 at 11:59 PM.",
    }

    result = await workflow.run(user_id=user.id, db=session, payload=extension_email)

    assert result["status"] == "completed"

    # Verify no duplicate task was created
    final_task_count = session.query(Task).filter(Task.user_id == user.id).count()
    assert final_task_count == initial_task_count

    # Verify the existing task's deadline and title were updated
    session.refresh(existing_task)
    assert existing_task.deadline.replace(tzinfo=timezone.utc) == new_due_date
    assert "Extended" in existing_task.title
    assert existing_task.priority == "high"

    # Verify deadline record was updated
    dl_rec = session.query(Deadline).filter(Deadline.task_id == existing_task.id).first()
    assert dl_rec.due_at.replace(tzinfo=timezone.utc) == new_due_date


    # Verify Telegram notification contains changes made
    assert mock_telegram.send_message.called
    sent_text = mock_telegram.send_message.call_args.kwargs["text"]
    assert "Updated deadline for" in sent_text


@pytest.mark.asyncio
async def test_conflict_detection_with_calendar(email_workflow_test_db):
    session, user = email_workflow_test_db

    # Late Lab Session is Sept 15, 2026, 22:00 to Sept 16, 00:30
    # Create an email with a deadline right inside this block
    deadline_at = datetime(2026, 9, 15, 23, 0, tzinfo=timezone.utc)

    mock_gemini = MagicMock()
    mock_gemini.reason_over_email = AsyncMock(
        return_value=EmailReasoningDecision(
            priority="urgent",
            requires_action=True,
            summary="Emergency quiz due during lab session.",
            reasoning="Due date directly overlaps with your scheduled Late Lab Session.",
            deadlines=[
                ExtractedDeadlineItem(
                    title="Urgent Quiz 3",
                    due_at=deadline_at,
                    source_context="Due Sept 15 at 11 PM",
                    is_hard_deadline=True,
                    confidence=0.99,
                )
            ],
            tasks_to_create=[
                ExtractedTaskItem(
                    title="Urgent Quiz 3",
                    description="Submit online quiz",
                    deadline=deadline_at,
                    priority="urgent",
                    category="exam",
                    estimated_effort_hours=1.0,
                    confidence=0.99,
                )
            ],
            tasks_to_update=[],
            events_to_create=[],
            detected_conflicts=["Deadline overlaps with scheduled Late Lab Session"],
            recommended_action="create_task",
            draft_response_needed=False,
            draft_response=None,
        )
    )

    mock_agent = MagicMock()
    mock_agent.gemini = mock_gemini
    mock_telegram = MagicMock()
    mock_telegram.send_message = AsyncMock()

    workflow = EmailToActionWorkflow(agent=mock_agent, telegram_adapter=mock_telegram)

    email_data = {
        "id": "gmail-conflict-01",
        "from": "instructor@univ.edu",
        "subject": "Surprise Quiz 3 Announced",
        "body": "Quiz 3 must be submitted before 11 PM on Sept 15.",
    }

    result = await workflow.run(user_id=user.id, db=session, payload=email_data)
    assert result["status"] == "completed"

    # Verify conflict was captured in changes
    assert any("conflict" in ch.lower() for ch in result["changes_made"])

    # Verify Telegram notification communicates the conflict
    sent_text = mock_telegram.send_message.call_args.kwargs["text"]
    assert "conflict" in sent_text.lower()


@pytest.mark.asyncio
async def test_non_actionable_low_priority_email_does_not_spam_telegram(email_workflow_test_db):
    session, user = email_workflow_test_db

    # Mock agent reasoning returning low priority with no action or deadlines
    mock_gemini = MagicMock()
    mock_gemini.reason_over_email = AsyncMock(
        return_value=EmailReasoningDecision(
            priority="low",
            requires_action=False,
            summary="Automated support confirmation ticket.",
            reasoning="This is an automated receipt. No student action is needed.",
            deadlines=[],
            tasks_to_create=[],
            tasks_to_update=[],
            events_to_create=[],
            detected_conflicts=[],
            recommended_action="no_action_needed",
            draft_response_needed=False,
            draft_response=None,
        )
    )

    mock_agent = MagicMock()
    mock_agent.gemini = mock_gemini
    mock_telegram = MagicMock()
    mock_telegram.send_message = AsyncMock()

    workflow = EmailToActionWorkflow(agent=mock_agent, telegram_adapter=mock_telegram)

    receipt_email = {
        "id": "gmail-receipt-999",
        "from": "support@service.com",
        "subject": "Ticket #8087052 Received - Account Closure",
        "body": "Your request has been received by our support team.",
    }

    result = await workflow.run(user_id=user.id, db=session, payload=receipt_email)
    assert result["status"] == "completed"

    # Verify email is saved as processed in DB
    email_rec = session.query(EmailMessage).filter(EmailMessage.gmail_id == "gmail-receipt-999").first()
    assert email_rec is not None
    assert email_rec.processing_status == "processed"
    assert email_rec.priority == "low"

    # Verify Telegram notification was NOT sent for non-actionable email
    assert not mock_telegram.send_message.called

