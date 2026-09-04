import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.telegram_adapter import TelegramAdapter
from app.models.calendar_event import CalendarEvent
from app.models.deadline import Deadline
from app.models.student_profile import User
from app.models.task import Task
from app.schemas.gemini_schemas import MorningBriefingResult
from app.services.audit_service import AuditService
from app.services.gemini_service import GeminiService

logger = logging.getLogger(__name__)


class BriefingService:
    """Service for compiling, generating, and dispatching morning briefings for students."""

    def __init__(
        self,
        gemini_service: GeminiService | None = None,
        telegram_adapter: TelegramAdapter | None = None,
    ) -> None:
        self.gemini = gemini_service or GeminiService()
        settings = get_settings()
        self.telegram = telegram_adapter or TelegramAdapter(settings)

    @staticmethod
    def gather_briefing_context(db: Session, user_id: int) -> dict[str, Any]:
        """Collect grounded local context: profile, pending tasks, upcoming deadlines, and today's schedule."""
        user = db.query(User).filter(User.id == user_id).first()
        profile = user.profile if user else None

        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        next_48h = now + timedelta(hours=48)

        # 1. Today's calendar commitments
        events = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.user_id == user_id,
                CalendarEvent.starts_at >= start_of_day,
                CalendarEvent.starts_at <= end_of_day,
            )
            .order_by(CalendarEvent.starts_at.asc())
            .all()
        )

        # 2. Active tasks
        tasks = (
            db.query(Task)
            .filter(
                Task.user_id == user_id,
                Task.status.in_(["pending", "in_progress"]),
            )
            .order_by(Task.deadline.asc().nullslast(), Task.priority.desc())
            .limit(10)
            .all()
        )

        # 3. Urgent deadlines within 48h
        deadlines = (
            db.query(Deadline)
            .filter(
                Deadline.user_id == user_id,
                Deadline.due_at >= now,
                Deadline.due_at <= next_48h,
            )
            .order_by(Deadline.due_at.asc())
            .all()
        )

        return {
            "student_name": user.full_name if user else "Student",
            "profile": profile,
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "priority": t.priority,
                    "deadline": t.deadline.isoformat() if t.deadline else None,
                    "category": t.category,
                }
                for t in tasks
            ],
            "calendar_events": [
                {
                    "title": e.title,
                    "starts_at": e.starts_at.isoformat(),
                    "ends_at": e.ends_at.isoformat(),
                    "location": e.location,
                }
                for e in events
            ],
            "urgent_deadlines": [
                {
                    "title": d.title,
                    "due_at": d.due_at.isoformat(),
                }
                for d in deadlines
            ],
        }

    async def generate_briefing(
        self,
        db: Session,
        user_id: int,
        send_notification: bool = False,
        chat_id: str | None = None,
    ) -> dict[str, Any]:
        """Compile context, ask Gemini for structured briefing, and optionally dispatch to Telegram."""
        workflow_id = f"briefing-{uuid.uuid4().hex[:8]}"
        context = self.gather_briefing_context(db, user_id)

        # 1. Ask Gemini to reason and structure the briefing
        briefing: MorningBriefingResult = await self.gemini.generate_morning_briefing(
            student_name=context["student_name"],
            profile=context["profile"],
            tasks=context["tasks"],
            calendar_events=context["calendar_events"],
        )

        # 2. Format plain text for notification
        formatted_message = (
            f"🌅 {briefing.greeting}\n\n"
            f"💡 Mindset: \"{briefing.quote_or_motto or 'Focus on what matters.'}\"\n\n"
            f"🎯 Top Priorities Today:\n" + "\n".join(f"• {p}" for p in briefing.top_priorities) + "\n\n"
            f"📅 Today's Timeline:\n{briefing.schedule_overview}"
        )
        if briefing.urgent_alerts:
            formatted_message += "\n\n⚠️ Upcoming Cutoffs:\n" + "\n".join(f"• {a}" for a in briefing.urgent_alerts)
        if briefing.recommended_recovery_action:
            formatted_message += f"\n\n🛠️ Pro-tip: {briefing.recommended_recovery_action}"

        delivery_status = "not_requested"
        mocked_delivery = True

        # 3. Dispatch notification if requested
        if send_notification:
            try:
                msg = await self.telegram.send_message(text=formatted_message, chat_id=chat_id)
                delivery_status = "sent"
                mocked_delivery = msg.mocked
            except Exception as err:
                logger.error("Failed to send briefing via Telegram: %s", err)
                delivery_status = f"failed: {err}"

        # 4. Log audit and activity
        AuditService.log_agent_action(
            db=db,
            user_id=user_id,
            tool_name="morning_briefing_workflow",
            status="success",
            workflow_id=workflow_id,
            input_params={"send_notification": send_notification},
            output_result={"priorities_count": len(briefing.top_priorities), "delivery": delivery_status},
        )
        AuditService.log_user_activity(
            db=db,
            user_id=user_id,
            activity_type="morning_briefing_generated",
            message=f"Generated morning briefing: {len(briefing.top_priorities)} priorities",
            metadata={
                "workflow_id": workflow_id,
                "delivery_status": delivery_status,
                "briefing_preview": briefing.schedule_overview[:120],
            },
        )

        return {
            "workflow_id": workflow_id,
            "status": "completed",
            "student_name": context["student_name"],
            "briefing": briefing.model_dump(),
            "formatted_text": formatted_message,
            "delivery_status": delivery_status,
            "mocked_delivery": mocked_delivery,
            "tasks_count": len(context["tasks"]),
            "events_today_count": len(context["calendar_events"]),
        }
