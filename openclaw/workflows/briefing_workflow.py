import logging
from typing import Any
from sqlalchemy.orm import Session

from openclaw.workflows.base_workflow import BaseWorkflow

logger = logging.getLogger(__name__)


class MorningBriefingWorkflow(BaseWorkflow):
    """Workflow to generate daily morning briefings and notify the student."""

    def __init__(self, agent=None) -> None:
        super().__init__(name="morning_briefing", agent=agent)

    async def run(self, user_id: int, db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        workflow_id = self.generate_workflow_id()
        self.log_workflow_start(db, user_id, workflow_id, "Generating student morning briefing")

        # 1. Gather context
        context = await self.agent.get_student_context(user_id, db)
        student_name = context.get("profile", {}).get("full_name", "")

        # 2. Reason via Gemini
        briefing = await self.agent.gemini.generate_morning_briefing(
            student_name=student_name,
            profile=context.get("profile"),
            tasks=context.get("tasks", []),
            calendar_events=context.get("calendar", []),
            urgent_deadlines=context.get("deadlines", []),
        )

        # 3. Format message and trigger notification tool (which requests approval if configured)
        briefing_text = (
            f"{briefing.greeting}\n\n"
            f"🎯 Top Priorities:\n" + "\n".join(f"• {p}" for p in briefing.top_priorities) + "\n\n"
            f"📅 Today's Rhythm:\n{briefing.schedule_overview}"
        )
        if briefing.urgent_alerts:
            briefing_text += "\n\n⚠️ Urgent Alerts:\n" + "\n".join(f"• {a}" for a in briefing.urgent_alerts)

        send_resp = await self.agent.run_tool(
            "send_telegram_message",
            {"text": briefing_text},
            user_id,
            db,
            workflow_id=workflow_id,
            approved=payload.get("approved", False) if payload else False,
        )

        self.log_workflow_complete(
            db,
            user_id,
            workflow_id,
            "Morning briefing generated",
            metadata={"priorities_count": len(briefing.top_priorities)},
        )

        return {
            "workflow_id": workflow_id,
            "status": "completed",
            "briefing": briefing.model_dump(),
            "notification_status": send_resp.get("status"),
        }
