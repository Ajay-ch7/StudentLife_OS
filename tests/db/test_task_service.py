from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.deadline import Deadline
from app.models.student_profile import User
from app.schemas.task import TaskInput, TaskUpdate
from app.services.task_service import create_task, delete_task, is_overdue, update_task


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(User(email="student@example.com", full_name="Student"))
    db.commit()
    yield db
    db.close()


def test_task_validation_duplicate_and_deadline_sync(session):
    user = session.query(User).one()
    task = create_task(session, user.id, TaskInput(title="Submit assignment", deadline=datetime(2026, 9, 10)))

    assert task.deadline is not None
    deadline = session.query(Deadline).one()
    assert deadline.task_id == task.id
    assert deadline.is_confirmed
    with pytest.raises(ValueError, match="already exists"):
        create_task(session, user.id, TaskInput(title=" submit ASSIGNMENT "))


def test_overdue_ignores_completed_tasks(session):
    user = session.query(User).one()
    task = create_task(session, user.id, TaskInput(title="Past task", deadline=datetime.now(timezone.utc) - timedelta(days=1)))
    assert is_overdue(task)
    task = update_task(session, task, TaskUpdate(status="completed"))
    assert not is_overdue(task)


def test_only_terminal_tasks_can_be_deleted(session):
    user = session.query(User).one()
    task = create_task(session, user.id, TaskInput(title="Active task"))
    with pytest.raises(ValueError, match="completed or cancelled"):
        delete_task(session, task)
    task = update_task(session, task, TaskUpdate(status="cancelled"))
    delete_task(session, task)
    assert session.get(type(task), task.id) is None