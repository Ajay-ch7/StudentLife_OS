from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.student_profile import User
from app.models.task import Task
from app.schemas.calendar import AvailabilityRequest, AvailabilityWindow, CalendarEventInput, CalendarEventUpdate
from app.services.scheduling_service import create_event, find_available_blocks, update_event


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(User(email="calendar@example.com", full_name="Calendar Student"))
    db.commit()
    yield db
    db.close()


def event_input(start: datetime, end: datetime, **values) -> CalendarEventInput:
    return CalendarEventInput(title="Study block", starts_at=start, ends_at=end, event_type="study", **values)


def test_overlapping_events_are_rejected(session):
    user = session.query(User).one()
    start = datetime(2026, 9, 4, 9, tzinfo=timezone.utc)
    create_event(session, user.id, event_input(start, start + timedelta(hours=1)))

    with pytest.raises(ValueError, match="overlaps"):
        create_event(session, user.id, event_input(start + timedelta(minutes=30), start + timedelta(hours=2)))


def test_event_cannot_run_past_linked_task_deadline(session):
    user = session.query(User).one()
    task = Task(user_id=user.id, title="Exam preparation", deadline=datetime(2026, 9, 4, 10, tzinfo=timezone.utc))
    session.add(task)
    session.commit()

    with pytest.raises(ValueError, match="task deadline"):
        create_event(session, user.id, event_input(datetime(2026, 9, 4, 9, 30, tzinfo=timezone.utc), datetime(2026, 9, 4, 10, 30, tzinfo=timezone.utc), task_id=task.id))


def test_availability_excludes_existing_event(session):
    user = session.query(User).one()
    window_start = datetime(2026, 9, 4, 9, tzinfo=timezone.utc)
    create_event(session, user.id, event_input(window_start + timedelta(hours=1), window_start + timedelta(hours=2)))

    blocks = find_available_blocks(
        session,
        user.id,
        AvailabilityRequest(windows=[AvailabilityWindow(starts_at=window_start, ends_at=window_start + timedelta(hours=3))], duration_minutes=60),
    )
    assert blocks == [(window_start, window_start + timedelta(hours=1)), (window_start + timedelta(hours=2), window_start + timedelta(hours=3))]


def test_rescheduling_into_conflict_is_rejected(session):
    user = session.query(User).one()
    start = datetime(2026, 9, 4, 9, tzinfo=timezone.utc)
    first = create_event(session, user.id, event_input(start, start + timedelta(hours=1)))
    create_event(session, user.id, event_input(start + timedelta(hours=2), start + timedelta(hours=3)))

    with pytest.raises(ValueError, match="overlaps"):
        update_event(session, first, CalendarEventUpdate(title=first.title, starts_at=start + timedelta(hours=2, minutes=15), ends_at=start + timedelta(hours=3, minutes=15), event_type=first.event_type))