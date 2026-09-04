from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.study_session import StudySession
from openclaw.workflows.base_workflow import BaseWorkflow


class EndOfDayReviewWorkflow(BaseWorkflow):
    """Detect missed study sessions and surface an approval-gated recovery proposal."""

    def __init__(self, agent=None) -> None:
        super().__init__(name="end_of_day_review", agent=agent)

    async def run(self, user_id: int, db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        workflow_id = self.generate_workflow_id()
        self.log_workflow_start(db, user_id, workflow_id, "Reviewing study sessions for recovery")
        now = datetime.now(timezone.utc)
        missed = (
            db.query(StudySession)
            .filter(
                StudySession.user_id == user_id,
                StudySession.planned_end < now,
                StudySession.status.in_(["planned", "in_progress"]),
            )
            .all()
        )
        for item in missed:
            item.status = "missed"
        if missed:
            db.commit()
        result = {"workflow_id": workflow_id, "status": "completed", "missed_session_ids": [item.id for item in missed], "recovery_required": bool(missed)}
        self.log_workflow_complete(db, user_id, workflow_id, "End-of-day review completed", {"missed_count": len(missed)})
        return result
