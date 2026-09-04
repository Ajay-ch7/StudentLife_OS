import logging
from typing import Any
from sqlalchemy.orm import Session

from openclaw.workflows.base_workflow import BaseWorkflow

logger = logging.getLogger(__name__)


class InboxProcessingWorkflow(BaseWorkflow):
    """Workflow to process incoming emails, messages, or files into verified tasks and deadlines."""

    def __init__(self, agent=None) -> None:
        super().__init__(name="inbox_processing", agent=agent)

    async def run(self, user_id: int, db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        raw_content = payload.get("content", "")
        file_path = payload.get("file_path")
        workflow_id = self.generate_workflow_id()

        self.log_workflow_start(
            db, user_id, workflow_id, f"Processing incoming content from {payload.get('source', 'document')}"
        )

        # 1. Read file if file_path is provided
        if file_path and not raw_content:
            doc_resp = await self.agent.run_tool(
                "parse_document", {"file_path": file_path}, user_id, db, workflow_id=workflow_id
            )
            if doc_resp.get("status") == "success":
                raw_content = doc_resp.get("result", {}).get("content_snippet", "")
            else:
                return {
                    "workflow_id": workflow_id,
                    "status": "error",
                    "error": doc_resp.get("error", "Failed to parse document"),
                }

        if not raw_content:
            return {"workflow_id": workflow_id, "status": "error", "error": "No content provided"}

        # 2. Extract structured tasks and deadlines using Gemini
        extraction = await self.agent.gemini.extract_tasks_and_deadlines(
            content=raw_content, source_type=payload.get("source", "document")
        )

        created_tasks = []
        # 3. Create verified tasks in SQLite via typed tool
        for task in extraction.tasks:
            if task.confidence >= 0.7:
                create_resp = await self.agent.run_tool(
                    "create_task",
                    {
                        "title": task.title,
                        "description": task.description,
                        "deadline": task.deadline.isoformat() if task.deadline else None,
                        "priority": task.priority,
                        "category": task.category,
                        "estimated_effort_hours": task.estimated_effort_hours,
                        "source": payload.get("source", "inbox"),
                    },
                    user_id,
                    db,
                    workflow_id=workflow_id,
                )
                if create_resp.get("status") == "success":
                    created_tasks.append(create_resp.get("result"))

        self.log_workflow_complete(
            db,
            user_id,
            workflow_id,
            f"Inbox processed: extracted {len(created_tasks)} tasks",
            metadata={"tasks_created": len(created_tasks)},
        )

        return {
            "workflow_id": workflow_id,
            "status": "completed",
            "summary": extraction.summary,
            "tasks_extracted": len(extraction.tasks),
            "tasks_created": created_tasks,
        }
