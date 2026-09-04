import json
import logging
from typing import Any
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.agent_action import AgentAction

logger = logging.getLogger(__name__)


class AuditService:
    """Service for logging agent tool executions and user activity to SQLite."""

    @staticmethod
    def log_agent_action(
        db: Session,
        user_id: int | None,
        tool_name: str,
        status: str,
        workflow_id: str | None = None,
        input_params: dict[str, Any] | None = None,
        output_result: Any = None,
    ) -> AgentAction:
        """Create an auditable record of an agent action."""
        input_summary = json.dumps(input_params, default=str) if input_params else None
        output_summary = (
            json.dumps(output_result, default=str)
            if isinstance(output_result, (dict, list))
            else str(output_result)
            if output_result is not None
            else None
        )
        # Limit length if huge
        if input_summary and len(input_summary) > 2000:
            input_summary = input_summary[:1997] + "..."
        if output_summary and len(output_summary) > 2000:
            output_summary = output_summary[:1997] + "..."

        action = AgentAction(
            user_id=user_id,
            workflow_id=workflow_id,
            tool_name=tool_name,
            status=status,
            input_summary=input_summary,
            output_summary=output_summary,
        )
        db.add(action)
        db.commit()
        db.refresh(action)
        return action

    @staticmethod
    def log_user_activity(
        db: Session,
        user_id: int | None,
        activity_type: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> ActivityLog:
        """Log a user-facing event into the activity feed."""
        metadata_json = json.dumps(metadata, default=str) if metadata else None
        log_entry = ActivityLog(
            user_id=user_id,
            activity_type=activity_type,
            message=message,
            metadata_json=metadata_json,
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        return log_entry
