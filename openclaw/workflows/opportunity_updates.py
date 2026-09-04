from typing import Any
from sqlalchemy.orm import Session
from openclaw.workflows.base_workflow import BaseWorkflow


class OpportunityUpdateWorkflow(BaseWorkflow):
    """Prepare a concise opportunity update; outbound delivery remains approval-gated."""

    def __init__(self, agent=None) -> None:
        super().__init__(name="opportunity_updates", agent=agent)

    async def run(self, user_id: int, db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        workflow_id = self.generate_workflow_id()
        self.log_workflow_start(db, user_id, workflow_id, "Preparing opportunity updates")
        message = (payload or {}).get("message", "New opportunity matches are available in your career workspace.")
        response = await self.agent.run_tool("send_telegram_message", {"text": message}, user_id, db, workflow_id=workflow_id)
        self.log_workflow_complete(db, user_id, workflow_id, "Opportunity update prepared")
        return {"workflow_id": workflow_id, "status": response.get("status", "completed"), "delivery": response}