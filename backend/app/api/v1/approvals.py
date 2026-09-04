import json
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.models.approval_request import ApprovalRequest
from app.models.application import Application
from app.models.study_session import StudySession
from app.schemas.approvals import ApprovalAction, ApprovalCreate
from app.schemas.common import ApprovalResponse
from app.services.approval_service import ApprovalService
from app.tools.tool_registry import tool_registry
from app.services.scheduling_service import create_event
from app.schemas.calendar import CalendarEventInput

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalResponse])
def list_approvals(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[ApprovalRequest]:
    requests = db.query(ApprovalRequest).filter(ApprovalRequest.user_id == user_id).order_by(ApprovalRequest.requested_at.desc()).all()
    return [ApprovalService.expire_if_needed(db, request) for request in requests]


@router.post("", response_model=ApprovalResponse)
def create_approval(payload: ApprovalCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> ApprovalResponse:
    return ApprovalService.create(db, user_id, **payload.model_dump())


def _resolve(request_id: int, status: str, payload: ApprovalAction, user_id: int, db: Session) -> ApprovalRequest:
    request = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id, ApprovalRequest.user_id == user_id).first()
    if request is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    try:
        return ApprovalService.resolve(db, request, status, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/{request_id}/approve", response_model=ApprovalResponse)
async def approve(request_id: int, payload: ApprovalAction, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> ApprovalResponse:
    request = _resolve(request_id, "approved", payload, user_id, db)
    metadata = json.loads(request.metadata_json) if request.metadata_json else {}
    tool_name = metadata.get("tool_name")
    if tool_name:
        result = await tool_registry.execute_tool(
            name=tool_name,
            parameters=metadata.get("parameters", {}),
            user_id=user_id,
            db=db,
            approved=True,
        )
        ApprovalService.record_result(db, request, result.model_dump())
    elif request.action_type == "orchestrated_plan":
        from app.services.orchestrator import multi_agent_orchestrator
        exec_results = await multi_agent_orchestrator.execute_approved_plan(db, user_id, request)
        ApprovalService.record_result(db, request, {"status": "executed", "results": exec_results})
    elif request.action_type == "submit_application":
        metadata = json.loads(request.metadata_json) if request.metadata_json else {}
        application = db.query(Application).filter(
            Application.id == metadata.get("application_id"),
            Application.user_id == user_id,
        ).first()
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        application.status = "submitted"
        db.commit()
        ApprovalService.record_result(db, request, {"application_id": application.id, "status": "submitted"})
    elif request.action_type == "reschedule_missed_sessions":
        metadata = json.loads(request.metadata_json) if request.metadata_json else {}
        sessions = db.query(StudySession).filter(StudySession.user_id == user_id, StudySession.id.in_(metadata.get("session_ids", []))).all()
        replacement_ids = []
        next_start = datetime.now(timezone.utc) + timedelta(days=1)
        for session in sessions:
            duration = session.planned_end - session.planned_start
            next_end = next_start + duration
            event = create_event(db, user_id, CalendarEventInput(title=f"Recovery: {session.topic}", starts_at=next_start, ends_at=next_end, event_type="study", task_id=session.task_id))
            session.planned_start = next_start
            session.planned_end = next_end
            session.status = "planned"
            replacement_ids.append(event.id)
            next_start = next_end + timedelta(minutes=15)
        db.commit()
        ApprovalService.record_result(db, request, {"replacement_event_ids": replacement_ids})
    return request


@router.put("/{request_id}/reject", response_model=ApprovalResponse)
def reject(request_id: int, payload: ApprovalAction, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> ApprovalResponse:
    return _resolve(request_id, "rejected", payload, user_id, db)


@router.put("/{request_id}/expire", response_model=ApprovalResponse)
def expire(request_id: int, payload: ApprovalAction, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> ApprovalResponse:
    return _resolve(request_id, "expired", payload, user_id, db)


@router.put("/{request_id}/retry", response_model=ApprovalResponse)
def retry(request_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> ApprovalResponse:
    request = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id, ApprovalRequest.user_id == user_id).first()
    if request is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    try:
        return ApprovalService.retry(db, request)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc