from typing import Any
from sqlalchemy.orm import Session

from app.services.briefing_service import BriefingService


class MorningBriefingWorkflowRunner:
    """Workflow runner for generating and dispatching daily student briefings."""

    def __init__(self, briefing_service: BriefingService | None = None) -> None:
        self.service = briefing_service or BriefingService()

    async def execute(
        self,
        db: Session,
        user_id: int,
        send_notification: bool = False,
        chat_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.service.generate_briefing(
            db=db,
            user_id=user_id,
            send_notification=send_notification,
            chat_id=chat_id,
        )
