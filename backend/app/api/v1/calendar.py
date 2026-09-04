from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.schemas.calendar import AvailabilityRequest, AvailableBlock, CalendarEventInput, CalendarEventResponse, CalendarEventUpdate, ConflictResponse, RescheduleInput
from app.services.scheduling_service import conflict_reasons, create_event, find_available_blocks, get_event_for_user, list_events, update_event

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("", response_model=list[CalendarEventResponse])
def get_calendar(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list:
    return list_events(db, user_id)


@router.post("/events", response_model=CalendarEventResponse, status_code=status.HTTP_201_CREATED)
def add_event(payload: CalendarEventInput, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> CalendarEventResponse:
    try:
        return create_event(db, user_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.put("/events/{event_id}", response_model=CalendarEventResponse)
def edit_event(event_id: int, payload: CalendarEventUpdate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> CalendarEventResponse:
    event = get_event_for_user(db, user_id, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Calendar event not found")
    try:
        return update_event(db, event, payload)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/conflicts", response_model=ConflictResponse)
def detect_conflicts(payload: CalendarEventInput, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> ConflictResponse:
    reasons = conflict_reasons(db, user_id, payload.starts_at, payload.ends_at, task_id=payload.task_id)
    return ConflictResponse(has_conflict=bool(reasons), reasons=reasons)


@router.post("/availability", response_model=list[AvailableBlock])
def get_availability(payload: AvailabilityRequest, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[AvailableBlock]:
    return [AvailableBlock(starts_at=start, ends_at=end) for start, end in find_available_blocks(db, user_id, payload)]


@router.post("/reschedule", response_model=CalendarEventResponse)
def reschedule_event(payload: RescheduleInput, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> CalendarEventResponse:
    event = get_event_for_user(db, user_id, payload.event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Calendar event not found")
    replacement = CalendarEventUpdate(
        title=event.title,
        description=event.description,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        event_type=event.event_type,
        location=event.location,
        task_id=event.task_id,
    )
    try:
        return update_event(db, event, replacement)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error