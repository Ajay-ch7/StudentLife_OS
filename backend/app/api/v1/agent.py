from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.models.activity_log import ActivityLog
from app.models.agent_action import AgentAction
from openclaw.workflows.briefing_workflow import MorningBriefingWorkflow
from openclaw.workflows.email_to_action_workflow import EmailToActionWorkflow
from openclaw.workflows.inbox_workflow import InboxProcessingWorkflow
from openclaw.workflows.opportunity_workflow import OpportunityEvaluationWorkflow
from openclaw.workflows.dsa_workflow import DSARecommendationWorkflow
from openclaw.workflows.end_of_day_review import EndOfDayReviewWorkflow
from openclaw.workflows.course_planning import CoursePlanningWorkflow
from openclaw.workflows.opportunity_updates import OpportunityUpdateWorkflow

router = APIRouter(prefix="/agent", tags=["agent"])

WORKFLOWS = {
    "inbox_processing": InboxProcessingWorkflow,
    "email_to_action": EmailToActionWorkflow,
    "morning_briefing": MorningBriefingWorkflow,
    "opportunity_evaluation": OpportunityEvaluationWorkflow,
    "dsa_recommendation": DSARecommendationWorkflow,
    "end_of_day_review": EndOfDayReviewWorkflow,
    "course_planning": CoursePlanningWorkflow,
    "opportunity_updates": OpportunityUpdateWorkflow,
}


class RunWorkflowRequest(BaseModel):
    workflow_name: Literal[
        "inbox_processing",
        "email_to_action",
        "morning_briefing",
        "opportunity_evaluation",
        "dsa_recommendation",
        "end_of_day_review",
        "course_planning",
        "opportunity_updates",
    ]
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


@router.get("/context")
async def get_agent_context(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Inspect the live context and data that OpenClaw agents receive and reason over."""
    from openclaw.agent.student_life_agent import StudentLifeAgent
    agent = StudentLifeAgent()
    context = await agent.get_student_context(user_id=user_id, db=db)
    return {
        "user_id": user_id,
        "context": context,
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


class ExplainDecisionRequest(BaseModel):
    query: str | None = Field(default=None, description="User's natural language question or why/explain prompt")
    decision_id: int | None = Field(default=None, description="Optional ID of the decision or email to explain")
    decision_type: str | None = Field(default=None, description="Optional type of decision: 'email', 'action', or 'activity'")


class ExplainDecisionResponse(BaseModel):
    success: bool
    decision_id: int | None
    decision_type: str | None
    decision_summary: str | None
    brief_reason: str | None
    explanation: str
    provider: str = "featherless_ai"
    model: str


@router.post("/explain", response_model=ExplainDecisionResponse)
async def explain_decision(
    request: ExplainDecisionRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> ExplainDecisionResponse:
    """
    On-demand model decision explanation powered by Featherless AI.
    Strictly bypasses Gemini API and returns a concise, grounded explanation
    of what decision was made, why it was made, and what factors/constraints influenced it.
    """
    from app.services.decision_context_service import DecisionContextService
    from app.services.featherless_service import FeatherlessService

    ctx = DecisionContextService.get_relevant_decision(
        user_id=user_id,
        db=db,
        query=request.query,
        decision_id=request.decision_id,
        decision_type=request.decision_type,
    )
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No relevant decision context found to explain.",
        )

    featherless = FeatherlessService()
    explanation = await featherless.explain_decision(ctx, user_query=request.query)

    return ExplainDecisionResponse(
        success=True,
        decision_id=ctx.get("decision_id"),
        decision_type=ctx.get("decision_type"),
        decision_summary=ctx.get("decision_summary"),
        brief_reason=ctx.get("brief_reason"),
        explanation=explanation,
        provider="featherless_ai",
        model=featherless.model,
    )

