from typing import Any

from sqlalchemy.orm import Session

from app.services.focus_service import FocusService
from openclaw.workflows.base_workflow import BaseWorkflow


class EndOfDayReviewWorkflow(BaseWorkflow):
    """Detect missed focus sessions and surface an approval-gated recovery proposal."""

    def __init__(self, agent=None) -> None:
        super().__init__(name="end_of_day_review", agent=agent)

    async def run(self, user_id: int, db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        workflow_id = self.generate_workflow_id()
        self.log_workflow_start(db, user_id, workflow_id, "Reviewing focus sessions for recovery")
        missed = FocusService.missed(db, user_id)
        result = {"workflow_id": workflow_id, "status": "completed", "missed_session_ids": [item.id for item in missed], "recovery_required": bool(missed)}
        self.log_workflow_complete(db, user_id, workflow_id, "End-of-day review completed", {"missed_count": len(missed)})
        return result
