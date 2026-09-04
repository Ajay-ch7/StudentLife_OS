from typing import Any

from sqlalchemy.orm import Session

from openclaw.workflows.base_workflow import BaseWorkflow


class CoursePlanningWorkflow(BaseWorkflow):
    """Plan from existing pending work without writing unvalidated calendar state."""

    def __init__(self, agent=None) -> None:
        super().__init__(name="course_planning", agent=agent)

    async def run(self, user_id: int, db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        workflow_id = self.generate_workflow_id()
        self.log_workflow_start(db, user_id, workflow_id, "Building an academic study plan")
        response = await self.agent.run_tool("generate_study_plan", payload or {}, user_id, db, workflow_id=workflow_id)
        self.log_workflow_complete(db, user_id, workflow_id, "Academic study plan generated")
        return {"workflow_id": workflow_id, "status": response.get("status", "completed"), "plan": response.get("result", {})}