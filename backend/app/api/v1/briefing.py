from typing import Any
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.models.activity_log import ActivityLog
from app.services.briefing_service import BriefingService

router = APIRouter(prefix="", tags=["briefing"])
briefing_service = BriefingService()


class MorningBriefingRequest(BaseModel):
    send_notification: bool = Field(False, description="Whether to dispatch via Telegram/mock channel")
    chat_id: str | None = Field(None, description="Optional custom Telegram chat ID")


class MorningBriefingResponse(BaseModel):
    workflow_id: str
    status: str
    student_name: str
    briefing: dict[str, Any]
    formatted_text: str
    delivery_status: str
    mocked_delivery: bool
    tasks_count: int
    events_today_count: int


@router.post("/workflows/morning-briefing", response_model=MorningBriefingResponse, status_code=status.HTTP_200_OK)
async def generate_morning_briefing(
    payload: MorningBriefingRequest = MorningBriefingRequest(),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MorningBriefingResponse:
    """Generate today's morning briefing with grounded tasks, schedule, and urgent alert summary."""
    result = await briefing_service.generate_briefing(
        db=db,
        user_id=user_id,
        send_notification=payload.send_notification,
        chat_id=payload.chat_id,
    )
    return MorningBriefingResponse(**result)


@router.get("/notifications", response_model=list[dict[str, Any]])
def get_notifications(
    limit: int = 20,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Retrieve recent notifications and briefings from the activity feed."""
    logs = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.user_id == user_id,
            ActivityLog.activity_type.in_([
                "morning_briefing_generated",
                "telegram_sent",
                "inbox_processed",
                "event_rescheduled",
                "approval_requested",
            ]),
        )
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": l.id,
            "type": l.activity_type,
            "message": l.message,
            "metadata": l.metadata_json,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]
