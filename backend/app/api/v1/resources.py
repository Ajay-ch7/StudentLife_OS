from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.models.activity_log import ActivityLog
from app.models.approval_request import ApprovalRequest
from app.models.calendar_event import CalendarEvent
from app.models.deadline import Deadline
from app.models.task import Task
from app.schemas.common import (
    ActivityResponse,
    ApprovalResponse,
    CalendarEventResponse,
    DeadlineResponse,
    TaskResponse,
)

router = APIRouter(tags=["workspace"])


@router.get("/tasks", response_model=list[TaskResponse])
def list_tasks(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[Task]:
    return db.query(Task).filter(Task.user_id == user_id).order_by(Task.deadline.asc(), Task.id.asc()).all()


@router.get("/deadlines", response_model=list[DeadlineResponse])
def list_deadlines(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[Deadline]:
    return db.query(Deadline).filter(Deadline.user_id == user_id).order_by(Deadline.due_at.asc()).all()


@router.get("/calendar", response_model=list[CalendarEventResponse])
def list_calendar(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[CalendarEvent]:
    return db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id).order_by(CalendarEvent.starts_at.asc()).all()


@router.get("/activity", response_model=list[ActivityResponse])
def list_activity(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[ActivityLog]:
    return db.query(ActivityLog).filter(ActivityLog.user_id == user_id).order_by(ActivityLog.created_at.desc()).all()


@router.get("/approvals", response_model=list[ApprovalResponse])
def list_approvals(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[ApprovalRequest]:
    return db.query(ApprovalRequest).filter(ApprovalRequest.user_id == user_id).order_by(ApprovalRequest.requested_at.desc()).all()