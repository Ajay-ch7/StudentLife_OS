from typing import Any
from sqlalchemy.orm import Session

from app.schemas.tools import ToolDefinition, ToolRunResponse
from app.tools.tool_registry import tool_registry


class OpenClawToolBridge:
    """Provides OpenClaw with access to typed backend tools with safety guarantees."""

    @staticmethod
    def get_tool_definitions() -> list[ToolDefinition]:
        """Fetch all available tool schemas for agent planning."""
        return tool_registry.get_schemas()

    @staticmethod
    async def invoke_tool(
        tool_name: str,
        parameters: dict[str, Any],
        user_id: int,
        db: Session,
        workflow_id: str | None = None,
        approved: bool = False,
    ) -> ToolRunResponse:
        """Safely invoke a backend tool on behalf of the agent."""
        return await tool_registry.execute_tool(
            name=tool_name,
            parameters=parameters,
            user_id=user_id,
            db=db,
            workflow_id=workflow_id,
            approved=approved,
        )
