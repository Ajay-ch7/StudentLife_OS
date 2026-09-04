import json
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.models.study_session import StudySession
from app.schemas.focus import FocusSessionCreate, FocusSessionEnd
from app.services.approval_service import ApprovalService
from app.services.focus_service import FocusService

router = APIRouter(prefix="/focus", tags=["focus"])


@router.post("/sessions")
def create_session(payload: FocusSessionCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    if payload.planned_end <= payload.planned_start:
        raise HTTPException(status_code=422, detail="planned_end must be after planned_start")
    session = StudySession(user_id=user_id, **payload.model_dump())
    db.add(session); db.commit(); db.refresh(session)
    return session


@router.put("/sessions/{session_id}/start")
def start_session(session_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    session = db.query(StudySession).filter(StudySession.id == session_id, StudySession.user_id == user_id).first()
    if session is None: raise HTTPException(status_code=404, detail="Focus session not found")
    try: return FocusService.start(db, session)
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/sessions/{session_id}/end")
def end_session(session_id: int, payload: FocusSessionEnd, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    session = db.query(StudySession).filter(StudySession.id == session_id, StudySession.user_id == user_id).first()
    if session is None: raise HTTPException(status_code=404, detail="Focus session not found")
    try: return FocusService.end(db, session, payload.actual_end)
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/recovery")
def recovery(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    missed = FocusService.missed(db, user_id)
    request = None
    if missed:
        request = ApprovalService.create(
            db, user_id, "reschedule_missed_sessions",
            f"Reschedule {len(missed)} missed focus session(s)",
            metadata_json=json.dumps({"session_ids": [item.id for item in missed]}),
        )
    return {"missed_sessions": missed, "approval_request_id": request.id if request else None, "status": "approval_required" if request else "clear"}