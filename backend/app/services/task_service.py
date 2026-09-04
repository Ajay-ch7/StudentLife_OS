from datetime import datetime, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.deadline import Deadline
from app.models.task import Task
from app.repositories.task_repository import task_repository
from app.schemas.task import TASK_STATUSES, TaskInput, TaskUpdate


STATUS_TRANSITIONS = {
    "pending": {"pending", "in_progress", "completed", "cancelled"},
    "in_progress": {"in_progress", "pending", "completed", "cancelled"},
    "completed": {"completed"},
    "cancelled": {"cancelled"},
}


def normalize_deadline(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_overdue(task: Task, *, now: datetime | None = None) -> bool:
    if task.deadline is None or task.status in {"completed", "cancelled"}:
        return False
    current = now or datetime.now(timezone.utc)
    deadline = normalize_deadline(task.deadline)
    return deadline is not None and deadline < current


def _find_duplicate(db: Session, user_id: int, title: str, *, exclude_id: int | None = None) -> Task | None:
    query = db.query(Task).filter(
        Task.user_id == user_id,
        func.lower(Task.title) == title.strip().lower(),
        Task.status != "cancelled",
    )
    if exclude_id is not None:
        query = query.filter(Task.id != exclude_id)
    return query.first()


def _sync_deadline(db: Session, task: Task) -> None:
    deadline = db.query(Deadline).filter(Deadline.task_id == task.id).first()
    if task.deadline is None:
        if deadline is not None:
            db.delete(deadline)
        return
    values = {
        "user_id": task.user_id,
        "task_id": task.id,
        "title": task.title,
        "due_at": task.deadline,
        "source": task.source,
        "is_confirmed": task.is_confirmed_deadline,
    }
    if deadline is None:
        db.add(Deadline(**values))
    else:
        for field, value in values.items():
            setattr(deadline, field, value)


def create_task(db: Session, user_id: int, payload: TaskInput) -> Task:
    if _find_duplicate(db, user_id, payload.title) is not None:
        raise ValueError("an active task with this title already exists")
    values = payload.model_dump()
    values["deadline"] = normalize_deadline(values["deadline"])
    task = task_repository.create(db, user_id=user_id, **values)
    _sync_deadline(db, task)
    db.commit()
    db.refresh(task)
    return task


def get_task_for_user(db: Session, user_id: int, task_id: int) -> Task | None:
    return db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()


def update_task(db: Session, task: Task, payload: TaskUpdate) -> Task:
    values = payload.model_dump(exclude_unset=True)
    if "title" in values and _find_duplicate(db, task.user_id, values["title"], exclude_id=task.id) is not None:
        raise ValueError("an active task with this title already exists")
    if "status" in values and values["status"] not in STATUS_TRANSITIONS[task.status]:
        raise ValueError(f"cannot change status from {task.status} to {values['status']}")
    if "deadline" in values:
        values["deadline"] = normalize_deadline(values["deadline"])
    for field, value in values.items():
        setattr(task, field, value)
    db.add(task)
    _sync_deadline(db, task)
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task: Task) -> None:
    if task.status not in {"completed", "cancelled"}:
        raise ValueError("only completed or cancelled tasks can be deleted")
    db.delete(task)
    db.commit()


def list_tasks(
    db: Session,
    user_id: int,
    *,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    overdue: bool | None = None,
    sort: str = "deadline",
) -> list[Task]:
    if status is not None and status not in TASK_STATUSES:
        raise ValueError("invalid status")
    query = db.query(Task).filter(Task.user_id == user_id)
    if status is not None:
        query = query.filter(Task.status == status)
    if priority is not None:
        query = query.filter(Task.priority == priority)
    if category is not None:
        query = query.filter(Task.category == category)
    if overdue is True:
        now = datetime.now(timezone.utc)
        query = query.filter(Task.deadline.is_not(None), Task.deadline < now, Task.status.not_in(["completed", "cancelled"]))
    elif overdue is False:
        now = datetime.now(timezone.utc)
        query = query.filter(or_(Task.deadline.is_(None), Task.deadline >= now, Task.status.in_(["completed", "cancelled"])))
    if sort == "created":
        query = query.order_by(Task.created_at.desc(), Task.id.desc())
    elif sort == "priority":
        query = query.order_by(Task.priority.desc(), Task.deadline.asc(), Task.id.asc())
    elif sort == "title":
        query = query.order_by(Task.title.asc(), Task.id.asc())
    else:
        query = query.order_by(Task.deadline.asc().nullslast(), Task.id.asc())
    return query.all()
