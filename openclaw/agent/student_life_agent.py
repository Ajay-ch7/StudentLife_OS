import logging
import uuid
import json
from typing import Any
from sqlalchemy.orm import Session

from app.services.audit_service import AuditService
from app.services.gemini_service import GeminiService
from openclaw.config import OpenClawConfig
from openclaw.tools.registry import OpenClawToolBridge

logger = logging.getLogger(__name__)


class StudentLifeAgent:
    """Core autonomous agent for Student Life OS, operating locally within strict safety boundaries."""

    def __init__(
        self,
        config: OpenClawConfig | None = None,
        gemini_service: GeminiService | None = None,
        tool_bridge: OpenClawToolBridge | None = None,
    ) -> None:
        self.config = config or OpenClawConfig()
        self.gemini = gemini_service or GeminiService()
        self.tools = tool_bridge or OpenClawToolBridge()

    async def get_student_context(self, user_id: int, db: Session) -> dict[str, Any]:
        """Fetch current minimal workspace context needed for reasoning."""
        profile_resp = await self.tools.invoke_tool("get_student_profile", {}, user_id, db)
        tasks_resp = await self.tools.invoke_tool("get_tasks", {"status": "pending"}, user_id, db)
        cal_resp = await self.tools.invoke_tool("get_calendar", {}, user_id, db)
        deadlines_resp = await self.tools.invoke_tool("get_deadlines", {"upcoming_only": True}, user_id, db)

        return {
            "profile": profile_resp.result if profile_resp.status == "success" else {},
            "tasks": tasks_resp.result if tasks_resp.status == "success" else [],
            "calendar": cal_resp.result if cal_resp.status == "success" else [],
            "deadlines": deadlines_resp.result if deadlines_resp.status == "success" else [],
        }

    async def run_tool(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        user_id: int,
        db: Session,
        workflow_id: str | None = None,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Execute a tool with error recovery and structured output."""
        wf_id = workflow_id or f"agent-wf-{uuid.uuid4().hex[:8]}"
        response = await self.tools.invoke_tool(
            tool_name=tool_name,
            parameters=parameters,
            user_id=user_id,
            db=db,
            workflow_id=wf_id,
            approved=approved,
        )

        if response.status == "approval_required":
            logger.info("Tool '%s' requires approval; creating approval request record.", tool_name)
            # Create an approval request so user can approve via dashboard
            await self.tools.invoke_tool(
                "create_approval_request",
                {
                    "action_type": tool_name,
                    "description": f"Agent wants to execute {tool_name} with parameters: {parameters}",
                    "metadata_json": json.dumps({"tool_name": tool_name, "parameters": parameters}, default=str),
                },
                user_id,
                db,
                workflow_id=wf_id,
            )

        return response.model_dump()
