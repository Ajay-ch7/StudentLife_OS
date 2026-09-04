from typing import Any

from sqlalchemy.orm import Session

from openclaw.workflows.base_workflow import BaseWorkflow


class DSARecommendationWorkflow(BaseWorkflow):
    """Produce a local DSA recommendation from persisted practice history."""

    def __init__(self, agent=None) -> None:
        super().__init__(name="dsa_recommendation", agent=agent)

    async def run(self, user_id: int, db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        workflow_id = self.generate_workflow_id()
        self.log_workflow_start(db, user_id, workflow_id, "Reviewing DSA practice progress")
        response = await self.agent.run_tool("get_dsa_progress", payload or {}, user_id, db, workflow_id=workflow_id)
        result = response.get("result", {})
        self.log_workflow_complete(db, user_id, workflow_id, "DSA progress reviewed", {"total_solved": result.get("total_solved", 0)})
        return {"workflow_id": workflow_id, "status": response.get("status", "completed"), "progress": result}
