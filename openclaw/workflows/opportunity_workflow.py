import logging
from typing import Any
from sqlalchemy.orm import Session

from openclaw.workflows.base_workflow import BaseWorkflow

logger = logging.getLogger(__name__)


class OpportunityEvaluationWorkflow(BaseWorkflow):
    """Workflow to analyze internship/job opportunities and propose actionable prep."""

    def __init__(self, agent=None) -> None:
        super().__init__(name="opportunity_evaluation", agent=agent)

    async def run(self, user_id: int, db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        opp_text = payload.get("opportunity_text", "")
        workflow_id = self.generate_workflow_id()

        self.log_workflow_start(db, user_id, workflow_id, "Evaluating career opportunity match")

        if not opp_text:
            # If no text passed, search top opportunity from tool
            search_resp = await self.agent.run_tool(
                "search_opportunities",
                {"query": payload.get("query", "software"), "limit": 1},
                user_id,
                db,
                workflow_id=workflow_id,
            )
            results = search_resp.get("result", [])
            if results:
                opp_text = f"{results[0]['title']} at {results[0]['company']}: {results[0]['description']}"
            else:
                return {"workflow_id": workflow_id, "status": "error", "error": "No opportunities found to evaluate"}

        # 1. Analyze fit via tool
        analysis_resp = await self.agent.run_tool(
            "analyze_opportunity",
            {"opportunity_text": opp_text},
            user_id,
            db,
            workflow_id=workflow_id,
        )

        analysis = analysis_resp.get("result", {})
        match_score = analysis.get("match_score", 0)

        # 2. If strong match, create a preparation task
        created_task = None
        if match_score >= 70:
            task_title = f"Apply & Prepare: {opp_text.split(':')[0]}"
            create_task_resp = await self.agent.run_tool(
                "create_task",
                {
                    "title": task_title,
                    "description": f"Fit score {match_score}%. Action items: {', '.join(analysis.get('action_items', []))}",
                    "priority": "high",
                    "category": "career",
                    "source": "opportunity_matcher",
                },
                user_id,
                db,
                workflow_id=workflow_id,
            )
            if create_task_resp.get("status") == "success":
                created_task = create_task_resp.get("result")

        self.log_workflow_complete(
            db,
            user_id,
            workflow_id,
            f"Opportunity analyzed: score {match_score}%",
            metadata={"match_score": match_score},
        )

        return {
            "workflow_id": workflow_id,
            "status": "completed",
            "analysis": analysis,
            "preparation_task": created_task,
        }
