from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.schemas.tools import ToolDefinition, ToolRunRequest, ToolRunResponse
from app.tools.tool_registry import tool_registry

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/schema", response_model=list[ToolDefinition])
def get_tool_schemas() -> list[ToolDefinition]:
    """Return OpenAPI / JSON schema definitions for all registered agent tools."""
    return tool_registry.get_schemas()


@router.post("/run", response_model=ToolRunResponse)
async def run_tool(
    payload: ToolRunRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> ToolRunResponse:
    """Execute a registered backend tool with safety checks, input validation, and audit logging."""
    return await tool_registry.execute_tool(
        name=payload.tool_name,
        parameters=payload.parameters,
        user_id=user_id,
        db=db,
        workflow_id=payload.workflow_id,
        approved=payload.approved,
    )
