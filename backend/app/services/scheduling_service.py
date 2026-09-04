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



HIGH_PRIORITY_KEYWORDS = {
    "interview", "exam", "assessment", "oa", "presentation", "test",
    "midterm", "final", "hiring", "recruiter", "onsite", "screening", "deadline",
}

LOW_PRIORITY_KEYWORDS = {
    "study", "learning plan", "dsa", "practice", "review", "reading",
    "prep", "exercise", "homework", "session", "revision", "self-study",
}


def is_high_priority_event(event: CalendarEvent, task: Task | None = None) -> bool:
    """Classify if a calendar event represents a high-priority, non-negotiable commitment."""
    if getattr(event, "event_type", "") in ("career", "exam"):
        return True
    title_lower = (event.title or "").lower()
    if any(kw in title_lower for kw in HIGH_PRIORITY_KEYWORDS):
        return True
    if task and task.priority in ("urgent", "high"):
        return True
    return False


def is_low_priority_event(event: CalendarEvent, task: Task | None = None) -> bool:
    """Classify if a calendar event is a flexible learning/study event eligible for shifting."""
    if is_high_priority_event(event, task):
        return False
    if getattr(event, "event_type", "") in ("study", "personal"):
        return True
    title_lower = (event.title or "").lower()
    if any(kw in title_lower for kw in LOW_PRIORITY_KEYWORDS):
        return True
    if task and task.priority in ("low", "medium"):
        return True
    return False


def find_candidate_free_slots(
    db: Session,
    user_id: int,
    days_ahead: int = 7,
    duration_minutes: int = 60,
    start_hour: int = 9,
    end_hour: int = 21,
) -> list[dict]:
    """
    Scan the next `days_ahead` days and find open, non-conflicting time windows
    between `start_hour` and `end_hour` that can accommodate `duration_minutes`.
    """
    now = datetime.now(timezone.utc)
    slots = []
    duration = timedelta(minutes=duration_minutes)

    for day_offset in range(days_ahead):
        day_date = (now + timedelta(days=day_offset)).date()
        day_events = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.user_id == user_id,
                CalendarEvent.starts_at >= datetime(day_date.year, day_date.month, day_date.day, 0, 0, 0, tzinfo=timezone.utc),
                CalendarEvent.starts_at <= datetime(day_date.year, day_date.month, day_date.day, 23, 59, 59, tzinfo=timezone.utc),
            )
            .order_by(CalendarEvent.starts_at.asc())
            .all()
        )

        has_high_priority = any(is_high_priority_event(e) for e in day_events)
        day_start = datetime(day_date.year, day_date.month, day_date.day, start_hour, 0, 0, tzinfo=timezone.utc)
        day_end = datetime(day_date.year, day_date.month, day_date.day, end_hour, 0, 0, tzinfo=timezone.utc)

        if day_date == now.date() and now > day_start:
            day_start = (now + timedelta(minutes=30)).replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)

        cursor = day_start
        while cursor + duration <= day_end:
            slot_end = cursor + duration
            overlaps = any(
                _overlaps(cursor, slot_end, normalize_datetime(e.starts_at), normalize_datetime(e.ends_at))
                for e in day_events
            )
            if not overlaps:
                slots.append({
                    "date": day_date.isoformat(),
                    "day_name": day_date.strftime("%A"),
                    "starts_at": cursor.isoformat(),
                    "ends_at": slot_end.isoformat(),
                    "has_high_priority_on_day": has_high_priority,
                    "existing_events_count": len(day_events),
                    "is_completely_free_day": len(day_events) == 0,
                })
            cursor += timedelta(minutes=60)

    slots.sort(key=lambda s: (s["has_high_priority_on_day"], s["existing_events_count"], s["starts_at"]))
    return slots


def detect_shiftable_low_priority_events(
    db: Session,
    user_id: int,
    days_ahead: int = 7,
) -> list[dict]:
    """
    Identifies low-priority calendar events (learning plans, study sessions) that
    either directly conflict with or crowd the same day as high-priority commitments (interviews, exams).
    Pairs each identified event with a suggested free slot on an alternative free day.
    """
    now = datetime.now(timezone.utc)
    future_limit = now + timedelta(days=days_ahead)

    all_events = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.starts_at >= now - timedelta(hours=1),
            CalendarEvent.starts_at <= future_limit,
        )
        .order_by(CalendarEvent.starts_at.asc())
        .all()
    )

    tasks_by_id = {t.id: t for t in db.query(Task).filter(Task.user_id == user_id).all()}

    high_pri_events = []
    low_pri_events = []

    for ev in all_events:
        linked_task = tasks_by_id.get(ev.task_id) if ev.task_id else None
        if is_high_priority_event(ev, linked_task):
            high_pri_events.append(ev)
        elif is_low_priority_event(ev, linked_task):
            low_pri_events.append(ev)

    candidate_slots = find_candidate_free_slots(db, user_id, days_ahead=days_ahead)
    shiftable = []

    for low_ev in low_pri_events:
        ev_start = normalize_datetime(low_ev.starts_at)
        ev_end = normalize_datetime(low_ev.ends_at)
        duration_minutes = int((ev_end - ev_start).total_seconds() // 60)
        if duration_minutes <= 0:
            duration_minutes = 60

        clash_event = None
        reason = None
        for high_ev in high_pri_events:
            h_start = normalize_datetime(high_ev.starts_at)
            h_end = normalize_datetime(high_ev.ends_at)
            if _overlaps(ev_start, ev_end, h_start, h_end):
                clash_event = high_ev
                reason = f"Directly overlaps with high-priority '{high_ev.title}'"
                break
            elif ev_start.date() == h_start.date():
                clash_event = high_ev
                reason = f"Shares busy interview/exam day with high-priority '{high_ev.title}'"
                break

        if clash_event and reason:
            target_slot = None
            # 1. Prefer a completely free day
            for slot in candidate_slots:
                slot_date = datetime.fromisoformat(slot["starts_at"]).date()
                if slot_date != ev_start.date() and slot.get("is_completely_free_day"):
                    target_slot = slot
                    break

            # 2. Otherwise a day without high priority events
            if not target_slot:
                for slot in candidate_slots:
                    slot_date = datetime.fromisoformat(slot["starts_at"]).date()
                    if slot_date != ev_start.date() and not slot["has_high_priority_on_day"]:
                        target_slot = slot
                        break

            if not target_slot and candidate_slots:
                for slot in candidate_slots:
                    slot_date = datetime.fromisoformat(slot["starts_at"]).date()
                    if slot_date != ev_start.date():
                        target_slot = slot
                        break

            new_start_iso = target_slot["starts_at"] if target_slot else None
            new_end_iso = (datetime.fromisoformat(new_start_iso) + timedelta(minutes=duration_minutes)).isoformat() if new_start_iso else None

            shiftable.append({
                "event_id": low_ev.id,
                "event_title": low_ev.title,
                "current_starts_at": ev_start.isoformat(),
                "current_ends_at": ev_end.isoformat(),
                "duration_minutes": duration_minutes,
                "conflicting_high_priority_event": {
                    "id": clash_event.id,
                    "title": clash_event.title,
                    "starts_at": normalize_datetime(clash_event.starts_at).isoformat(),
                },
                "conflict_reason": reason,
                "recommended_new_start": new_start_iso,
                "recommended_new_end": new_end_iso,
                "target_day_name": target_slot["day_name"] if target_slot else None,
                "target_is_free_day": target_slot.get("is_completely_free_day", False) if target_slot else False,
            })

    return shiftable


def get_management_context_snapshot(db: Session, user_id: int) -> dict:
    """Read-only Management Agent context snapshot for the Orchestrator. No writes."""
    now = datetime.now(timezone.utc)
    next_7_days = now + timedelta(days=7)

    # Upcoming calendar events in next 7 days
    upcoming_events = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.starts_at >= now,
            CalendarEvent.starts_at <= next_7_days,
        )
        .order_by(CalendarEvent.starts_at.asc())
        .limit(15)
        .all()
    )

    tasks_by_id = {t.id: t for t in db.query(Task).filter(Task.user_id == user_id).all()}

    upcoming_events_data = [
        {
            "id": e.id,
            "title": e.title,
            "starts_at": e.starts_at.isoformat(),
            "ends_at": e.ends_at.isoformat(),
            "event_type": e.event_type,
            "is_high_priority": is_high_priority_event(e, tasks_by_id.get(e.task_id)),
            "is_low_priority": is_low_priority_event(e, tasks_by_id.get(e.task_id)),
        }
        for e in upcoming_events
    ]

    # Task load breakdown
    all_pending = (
        db.query(Task)
        .filter(Task.user_id == user_id, Task.status == "pending")
        .all()
    )
    urgent_count = sum(1 for t in all_pending if t.priority == "urgent")
    high_count = sum(1 for t in all_pending if t.priority == "high")
    task_load = {
        "urgent": urgent_count,
        "high": high_count,
        "total_pending": len(all_pending),
    }

    # Conflict risk level
    if urgent_count >= 3 or len(all_pending) >= 10:
        conflict_risk_level = "high"
    elif urgent_count >= 1 or len(all_pending) >= 5:
        conflict_risk_level = "medium"
    else:
        conflict_risk_level = "low"

    # Free blocks today (hours not covered by calendar events)
    today_start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=22, minute=0, second=0, microsecond=0)
    today_events = [
        e for e in upcoming_events
        if e.starts_at.date() == now.date()
    ]
    free_blocks: list[list[str]] = []
    cursor = today_start
    for event in sorted(today_events, key=lambda e: e.starts_at):
        ev_start = event.starts_at.replace(tzinfo=timezone.utc) if event.starts_at.tzinfo is None else event.starts_at.astimezone(timezone.utc)
        ev_end = event.ends_at.replace(tzinfo=timezone.utc) if event.ends_at.tzinfo is None else event.ends_at.astimezone(timezone.utc)
        if cursor < ev_start:
            free_blocks.append([cursor.strftime("%H:%M"), ev_start.strftime("%H:%M")])
        cursor = max(cursor, ev_end)
    if cursor < today_end:
        free_blocks.append([cursor.strftime("%H:%M"), today_end.strftime("%H:%M")])

    # Low priority shift detection and candidate free days
    shiftable_events = detect_shiftable_low_priority_events(db, user_id, days_ahead=7)
    candidate_free_slots = find_candidate_free_slots(db, user_id, days_ahead=7)
    candidate_free_days = list(dict.fromkeys(s["date"] for s in candidate_free_slots if s.get("is_completely_free_day")))

    return {
        "upcoming_events": upcoming_events_data,
        "task_load": task_load,
        "free_blocks_today": free_blocks,
        "conflict_risk_level": conflict_risk_level,
        "shiftable_low_priority_events": shiftable_events,
        "candidate_free_days": candidate_free_days[:5],
        "candidate_free_slots": candidate_free_slots[:6],
    }


def check_incoming_event_conflicts(
    db: Session,
    user_id: int,
    starts_at: datetime,
    ends_at: datetime,
    incoming_title: str = "Upcoming Interview",
    days_ahead: int = 14,
) -> list[dict]:
    """
    Checks if an incoming high-priority event (like an interview or exam)
    overlaps with or conflicts with any existing low-priority calendar events (learning plans, study sessions).
    For each conflicting low-priority event, identifies a candidate free slot on another free day to shift to.
    """
    starts_at = normalize_datetime(starts_at)
    ends_at = normalize_datetime(ends_at)

    all_events = db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id).all()
    tasks_by_id = {t.id: t for t in db.query(Task).filter(Task.user_id == user_id).all()}

    conflicts = []
    for ev in all_events:
        ev_start = normalize_datetime(ev.starts_at)
        ev_end = normalize_datetime(ev.ends_at)
        linked_task = tasks_by_id.get(ev.task_id) if ev.task_id else None

        if _overlaps(starts_at, ends_at, ev_start, ev_end):
            # Is it a low-priority event or non-high priority flexible event?
            if is_low_priority_event(ev, linked_task) or not is_high_priority_event(ev, linked_task):
                duration_minutes = int((ev_end - ev_start).total_seconds() // 60)
                if duration_minutes <= 0:
                    duration_minutes = 60

                candidate_slots = find_candidate_free_slots(
                    db, user_id, days_ahead=days_ahead, duration_minutes=duration_minutes
                )

                target_slot = None
                # 1. Prefer a completely free day
                for slot in candidate_slots:
                    slot_date = datetime.fromisoformat(slot["starts_at"]).date()
                    if slot_date != starts_at.date() and slot.get("is_completely_free_day"):
                        target_slot = slot
                        break

                # 2. Otherwise a day without high-priority events
                if not target_slot:
                    for slot in candidate_slots:
                        slot_date = datetime.fromisoformat(slot["starts_at"]).date()
                        if slot_date != starts_at.date() and not slot["has_high_priority_on_day"]:
                            target_slot = slot
                            break

                if not target_slot and candidate_slots:
                    for slot in candidate_slots:
                        slot_date = datetime.fromisoformat(slot["starts_at"]).date()
                        if slot_date != starts_at.date():
                            target_slot = slot
                            break

                new_start_iso = target_slot["starts_at"] if target_slot else (starts_at + timedelta(days=1)).isoformat()
                new_end_iso = (datetime.fromisoformat(new_start_iso) + timedelta(minutes=duration_minutes)).isoformat()
                day_name = target_slot["day_name"] if target_slot else (starts_at + timedelta(days=1)).strftime("%A")
                is_free_day = target_slot.get("is_completely_free_day", False) if target_slot else True

                conflicts.append({
                    "event_id": ev.id,
                    "event_title": ev.title,
                    "is_shiftable": True,
                    "current_starts_at": ev_start.isoformat(),
                    "current_ends_at": ev_end.isoformat(),
                    "duration_minutes": duration_minutes,
                    "incoming_title": incoming_title,
                    "incoming_starts_at": starts_at.isoformat(),
                    "incoming_ends_at": ends_at.isoformat(),
                    "conflict_reason": f"Directly conflicts with incoming '{incoming_title}' ({starts_at.strftime('%a %b %d at %I:%M %p')})",
                    "recommended_new_start": new_start_iso,
                    "recommended_new_end": new_end_iso,
                    "target_day_name": day_name,
                    "target_is_free_day": is_free_day,
                })

    return conflicts