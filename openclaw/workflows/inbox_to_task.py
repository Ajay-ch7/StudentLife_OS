from typing import Any
from sqlalchemy.orm import Session

from app.services.inbox_service import InboxService
from openclaw.workflows.base_workflow import BaseWorkflow


class InboxToTaskWorkflow(BaseWorkflow):
    """OpenClaw workflow for turning unstructured inbox items into validated tasks and conflict alerts."""

    def __init__(self, inbox_service: InboxService | None = None) -> None:
        super().__init__(name="inbox_to_task")
        self.inbox_service = inbox_service or InboxService()

    async def run(self, user_id: int, db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        content = payload.get("content", "")
        source_type = payload.get("source_type", "email")
        dry_run = payload.get("dry_run", False)

        return await self.inbox_service.process_content(
            db=db,
            user_id=user_id,
            content=content,
            source_type=source_type,
            source_metadata=payload.get("metadata"),
            dry_run=dry_run,
        )
