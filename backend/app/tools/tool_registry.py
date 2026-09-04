import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.schemas.tools import (
    ToolAccessLevel,
    ToolDefinition,
    ToolRunResponse,
)
from app.services.audit_service import AuditService
from app.services.permission_service import (
    ApprovalRequiredError,
    PermissionDeniedError,
    PermissionService,
)

logger = logging.getLogger(__name__)


@dataclass
class RegisteredTool:
    name: str
    func: Callable[..., Any]
    input_model: type[BaseModel]
    access_level: ToolAccessLevel
    requires_approval: bool
    description: str


class ToolRegistry:
    """Central registry and execution manager for typed agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        name: str,
        input_model: type[BaseModel],
        access_level: ToolAccessLevel,
        requires_approval: bool = False,
        description: str = "",
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            desc = description or func.__doc__ or f"Tool {name}"
            self._tools[name] = RegisteredTool(
                name=name,
                func=func,
                input_model=input_model,
                access_level=access_level,
                requires_approval=requires_approval,
                description=desc.strip(),
            )
            return func

        return decorator

    def get_tool(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[RegisteredTool]:
        return list(self._tools.values())

    def get_schemas(self) -> list[ToolDefinition]:
        """Generate JSON schema declarations for all registered tools."""
        definitions: list[ToolDefinition] = []
        for tool in self._tools.values():
            schema = tool.input_model.model_json_schema()
            definitions.append(
                ToolDefinition(
                    name=tool.name,
                    description=tool.description,
                    access_level=tool.access_level,
                    requires_approval=tool.requires_approval,
                    parameters=schema,
                )
            )
        return definitions

    async def execute_tool(
        self,
        name: str,
        parameters: dict[str, Any],
        user_id: int,
        db: Session,
        workflow_id: str | None = None,
        approved: bool = False,
    ) -> ToolRunResponse:
        """Validate, check permissions, execute, and audit a tool call."""
        tool = self.get_tool(name)
        if not tool:
            return ToolRunResponse(
                tool_name=name,
                status="error",
                error=f"Tool '{name}' is not registered.",
            )

        # 1. Validate permissions and approval requirements
        try:
            PermissionService.check_tool_permission(
                tool_name=name,
                access_level=tool.access_level,
                requires_approval=tool.requires_approval,
                is_approved=approved,
            )
        except ApprovalRequiredError as exc:
            action = AuditService.log_agent_action(
                db=db,
                user_id=user_id,
                tool_name=name,
                status="approval_required",
                workflow_id=workflow_id,
                input_params=parameters,
            )
            return ToolRunResponse(
                tool_name=name,
                status="approval_required",
                error=str(exc),
                action_id=action.id,
            )
        except PermissionDeniedError as exc:
            action = AuditService.log_agent_action(
                db=db,
                user_id=user_id,
                tool_name=name,
                status="permission_denied",
                workflow_id=workflow_id,
                input_params=parameters,
            )
            return ToolRunResponse(
                tool_name=name,
                status="error",
                error=str(exc),
                action_id=action.id,
            )

        # 2. Validate input parameters against schema
        try:
            validated_input = tool.input_model.model_validate(parameters)
        except Exception as exc:
            action = AuditService.log_agent_action(
                db=db,
                user_id=user_id,
                tool_name=name,
                status="validation_error",
                workflow_id=workflow_id,
                input_params=parameters,
            )
            return ToolRunResponse(
                tool_name=name,
                status="error",
                error=f"Invalid arguments for {name}: {exc}",
                action_id=action.id,
            )

        # 3. Execute tool function
        try:
            # Check function signature to supply db and user_id if expected
            sig = inspect.signature(tool.func)
            kwargs: dict[str, Any] = {"payload": validated_input}
            if "user_id" in sig.parameters:
                kwargs["user_id"] = user_id
            if "db" in sig.parameters:
                kwargs["db"] = db

            if inspect.iscoroutinefunction(tool.func):
                result = await tool.func(**kwargs)
            else:
                result = tool.func(**kwargs)


            action = AuditService.log_agent_action(
                db=db,
                user_id=user_id,
                tool_name=name,
                status="success",
                workflow_id=workflow_id,
                input_params=parameters,
                output_result=result,
            )

            return ToolRunResponse(
                tool_name=name,
                status="success",
                result=result,
                action_id=action.id,
            )
        except Exception as exc:
            logger.exception("Error executing tool %s: %s", name, exc)
            action = AuditService.log_agent_action(
                db=db,
                user_id=user_id,
                tool_name=name,
                status="execution_error",
                workflow_id=workflow_id,
                input_params=parameters,
                output_result=str(exc),
            )
            return ToolRunResponse(
                tool_name=name,
                status="error",
                error=f"Execution error: {exc}",
                action_id=action.id,
            )


tool_registry = ToolRegistry()
