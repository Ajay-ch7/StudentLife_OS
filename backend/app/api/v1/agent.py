from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.models.activity_log import ActivityLog
from app.models.agent_action import AgentAction
from openclaw.workflows.briefing_workflow import MorningBriefingWorkflow
from openclaw.workflows.inbox_workflow import InboxProcessingWorkflow
from openclaw.workflows.opportunity_workflow import OpportunityEvaluationWorkflow
from openclaw.workflows.dsa_workflow import DSARecommendationWorkflow
from openclaw.workflows.end_of_day_review import EndOfDayReviewWorkflow
from openclaw.workflows.course_planning import CoursePlanningWorkflow
from openclaw.workflows.opportunity_updates import OpportunityUpdateWorkflow

router = APIRouter(prefix="/agent", tags=["agent"])

WORKFLOWS = {
    "inbox_processing": InboxProcessingWorkflow,
    "morning_briefing": MorningBriefingWorkflow,
    "opportunity_evaluation": OpportunityEvaluationWorkflow,
    "dsa_recommendation": DSARecommendationWorkflow,
    "end_of_day_review": EndOfDayReviewWorkflow,
    "course_planning": CoursePlanningWorkflow,
    "opportunity_updates": OpportunityUpdateWorkflow,
}


class RunWorkflowRequest(BaseModel):
    workflow_name: Literal["inbox_processing", "morning_briefing", "opportunity_evaluation", "dsa_recommendation", "end_of_day_review", "course_planning", "opportunity_updates"]
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowExecutionResponse(BaseModel):
    workflow_name: str
    status: str
    result: dict[str, Any]


@router.get("/status")
def get_agent_status() -> dict[str, Any]:
    """Check agent runtime status and available workflows."""
    return {
        "status": "ready",
        "agent": "OpenClaw Local Runtime",
        "available_workflows": list(WORKFLOWS.keys()),
    }


@router.post("/run-workflow", response_model=WorkflowExecutionResponse)
async def run_workflow(
    request: RunWorkflowRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> WorkflowExecutionResponse:
    """Trigger an autonomous agent workflow on demand."""
    workflow_cls = WORKFLOWS.get(request.workflow_name)
    if not workflow_cls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown workflow '{request.workflow_name}'",
        )

    workflow = workflow_cls()
    result = await workflow.run(user_id=user_id, db=db, payload=request.payload)
    return WorkflowExecutionResponse(
        workflow_name=request.workflow_name,
        status=result.get("status", "completed"),
        result=result,
    )


@router.get("/history")
def get_agent_history(
    limit: int = 20,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Retrieve recent agent actions."""
    actions = (
        db.query(AgentAction)
        .filter(AgentAction.user_id == user_id)
        .order_by(AgentAction.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": a.id,
            "tool_name": a.tool_name,
            "status": a.status,
            "workflow_id": a.workflow_id,
            "input_summary": a.input_summary,
            "output_summary": a.output_summary,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in actions
    ]
