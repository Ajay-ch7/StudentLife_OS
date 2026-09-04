import json
import logging
from typing import Any
from sqlalchemy.orm import Session

from app.models.email_message import EmailMessage
from app.models.agent_action import AgentAction
from app.models.activity_log import ActivityLog
from app.models.task import Task
from app.models.calendar_event import CalendarEvent

logger = logging.getLogger(__name__)


class DecisionContextService:
    """
    Locates and aggregates relevant context for an autonomous model decision
    from SQLite (EmailMessage, AgentAction, ActivityLog, Task, CalendarEvent).
    Provides grounded truth for Featherless AI explanation generation.
    """

    @staticmethod
    def get_relevant_decision(
        user_id: int,
        db: Session,
        query: str | None = None,
        decision_id: int | None = None,
        decision_type: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Find the most relevant decision to explain, either matching query keywords,
        explicit ID, or most recent autonomous action.
        """
        query_lower = (query or "").lower().strip()

        # 1. Direct lookup by ID and type if provided
        if decision_id:
            if decision_type == "email" or not decision_type:
                email = db.query(EmailMessage).filter(EmailMessage.id == decision_id, EmailMessage.user_id == user_id).first()
                if email:
                    return DecisionContextService._format_email_decision(email)

            if decision_type == "action" or not decision_type:
                action = db.query(AgentAction).filter(AgentAction.id == decision_id, AgentAction.user_id == user_id).first()
                if action:
                    return DecisionContextService._format_action_decision(action)

            if decision_type == "activity" or not decision_type:
                activity = db.query(ActivityLog).filter(ActivityLog.id == decision_id, ActivityLog.user_id == user_id).first()
                if activity:
                    return DecisionContextService._format_activity_decision(activity)

        # 2. Search recent processed emails (primary autonomous decision source)
        emails = (
            db.query(EmailMessage)
            .filter(
                EmailMessage.user_id == user_id,
                EmailMessage.reasoning.isnot(None),
                EmailMessage.processing_status == "processed",
            )
            .order_by(EmailMessage.processed_at.desc().nullslast(), EmailMessage.id.desc())
            .limit(10)
            .all()
        )

        if emails:
            # If user query has keywords, search for matching email subject or body
            if query_lower:
                for em in emails:
                    if (
                        query_lower in em.subject.lower()
                        or (em.reasoning and query_lower in em.reasoning.lower())
                        or (em.snippet and query_lower in em.snippet.lower())
                    ):
                        return DecisionContextService._format_email_decision(em)

            # Otherwise, return the most recent processed email decision
            if not query_lower or any(k in query_lower for k in ["last", "recent", "why", "explain", "decision"]):
                return DecisionContextService._format_email_decision(emails[0])

        # 3. Search recent AgentActions
        actions = (
            db.query(AgentAction)
            .filter(AgentAction.user_id == user_id)
            .order_by(AgentAction.created_at.desc())
            .limit(10)
            .all()
        )
        if actions:
            if query_lower:
                for act in actions:
                    text_blob = f"{act.tool_name} {act.input_summary or ''} {act.output_summary or ''}".lower()
                    if query_lower in text_blob:
                        return DecisionContextService._format_action_decision(act)
            if not emails:
                return DecisionContextService._format_action_decision(actions[0])

        # 4. Search recent ActivityLogs
        logs = (
            db.query(ActivityLog)
            .filter(ActivityLog.user_id == user_id)
            .order_by(ActivityLog.created_at.desc())
            .limit(10)
            .all()
        )
        if logs:
            if query_lower:
                for l in logs:
                    if query_lower in (l.message or "").lower():
                        return DecisionContextService._format_activity_decision(l)
            if not emails and not actions:
                return DecisionContextService._format_activity_decision(logs[0])

        return None

    @staticmethod
    def _format_email_decision(email: EmailMessage) -> dict[str, Any]:
        return {
            "decision_id": email.id,
            "decision_type": "email_to_action",
            "decision_summary": f"Processed email: '{email.subject}'",
            "action_taken": f"Set priority to '{email.priority}' and recommended action '{email.action_type or 'record_and_monitor'}'",
            "brief_reason": email.reasoning or "Email analyzed for deadlines and academic urgency.",
            "source_info": {
                "from": email.sender,
                "subject": email.subject,
                "date": email.date_str,
                "priority_assigned": email.priority,
                "requires_action": email.requires_action,
                "tasks_extracted": email.has_tasks_extracted,
                "processed_at": email.processed_at.isoformat() if email.processed_at else None,
            },
            "content_snippet": email.snippet or (email.body[:300] if email.body else "No body text available"),
        }

    @staticmethod
    def _format_action_decision(action: AgentAction) -> dict[str, Any]:
        return {
            "decision_id": action.id,
            "decision_type": "agent_action",
            "decision_summary": f"Executed tool '{action.tool_name}'",
            "action_taken": f"Action status: '{action.status}' for tool {action.tool_name}",
            "brief_reason": f"Tool execution triggered by autonomous workflow or user prompt.",
            "source_info": {
                "tool_name": action.tool_name,
                "status": action.status,
                "workflow_id": action.workflow_id,
                "input": action.input_summary,
                "output": action.output_summary,
                "created_at": action.created_at.isoformat() if action.created_at else None,
            },
        }

    @staticmethod
    def _format_activity_decision(log: ActivityLog) -> dict[str, Any]:
        meta = {}
        if log.metadata_json:
            try:
                meta = json.loads(log.metadata_json)
            except Exception:
                meta = {"raw": log.metadata_json}
        return {
            "decision_id": log.id,
            "decision_type": "activity_log",
            "decision_summary": f"Activity: {log.activity_type}",
            "action_taken": log.message,
            "brief_reason": meta.get("reason") or "Activity logged during autonomous workflow execution.",
            "source_info": {
                "activity_type": log.activity_type,
                "message": log.message,
                "metadata": meta,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            },
        }
