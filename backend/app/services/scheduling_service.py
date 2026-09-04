from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.calendar_event import CalendarEvent
from app.models.task import Task
from app.schemas.calendar import AvailabilityRequest, CalendarEventInput, CalendarEventUpdate


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _overlaps(left_start: datetime, left_end: datetime, right_start: datetime, right_end: datetime) -> bool:
    return left_start < right_end and right_start < left_end


def conflict_reasons(
    db: Session,
    user_id: int,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_event_id: int | None = None,
    task_id: int | None = None,
) -> list[str]:
    starts_at = normalize_datetime(starts_at)
    ends_at = normalize_datetime(ends_at)
    reasons: list[str] = []
    query = db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id)
    if exclude_event_id is not None:
        query = query.filter(CalendarEvent.id != exclude_event_id)
    for event in query.all():
        event_start = normalize_datetime(event.starts_at)
        event_end = normalize_datetime(event.ends_at)
        if _overlaps(starts_at, ends_at, event_start, event_end):
            reasons.append(f"overlaps '{event.title}' ({event_start.isoformat()} to {event_end.isoformat()})")
    if task_id is not None:
        task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
        if task is None:
            reasons.append("the selected task does not belong to this user")
        elif task.deadline is not None and ends_at > normalize_datetime(task.deadline):
            reasons.append("ends after the linked task deadline")
    return reasons


def create_event(db: Session, user_id: int, payload: CalendarEventInput) -> CalendarEvent:
    values = payload.model_dump()
    values["starts_at"] = normalize_datetime(values["starts_at"])
    values["ends_at"] = normalize_datetime(values["ends_at"])
    reasons = conflict_reasons(db, user_id, values["starts_at"], values["ends_at"], task_id=values["task_id"])
    if reasons:
        raise ValueError("; ".join(reasons))
    event = CalendarEvent(user_id=user_id, **values)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def update_event(db: Session, event: CalendarEvent, payload: CalendarEventUpdate) -> CalendarEvent:
    values = payload.model_dump()
    values["starts_at"] = normalize_datetime(values["starts_at"])
    values["ends_at"] = normalize_datetime(values["ends_at"])
    reasons = conflict_reasons(db, event.user_id, values["starts_at"], values["ends_at"], exclude_event_id=event.id, task_id=values["task_id"])
    if reasons:
        raise ValueError("; ".join(reasons))
    for field, value in values.items():
        setattr(event, field, value)
    db.commit()
    db.refresh(event)
    return event


def get_event_for_user(db: Session, user_id: int, event_id: int) -> CalendarEvent | None:
    return db.query(CalendarEvent).filter(CalendarEvent.id == event_id, CalendarEvent.user_id == user_id).first()


def list_events(db: Session, user_id: int) -> list[CalendarEvent]:
    return db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id).order_by(CalendarEvent.starts_at.asc(), CalendarEvent.id.asc()).all()


def find_available_blocks(db: Session, user_id: int, request: AvailabilityRequest) -> list[tuple[datetime, datetime]]:
    blocks: list[tuple[datetime, datetime]] = []
    duration = timedelta(minutes=request.duration_minutes)
    for window in request.windows:
        start = normalize_datetime(window.starts_at)
        window_end = normalize_datetime(window.ends_at)
        while start + duration <= window_end:
            end = start + duration
            if not conflict_reasons(db, user_id, start, end, task_id=request.task_id):
                blocks.append((start, end))
            start = end
    return blocks