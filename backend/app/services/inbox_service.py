import logging
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session

from app.models.calendar_event import CalendarEvent
from app.models.deadline import Deadline
from app.models.email_message import EmailMessage
from app.models.task import Task
from app.services.audit_service import AuditService
from app.services.gemini_service import GeminiService

logger = logging.getLogger(__name__)


class InboxService:
    """End-to-end service for processing incoming emails, messages, and documents into validated tasks."""

    def __init__(self, gemini_service: GeminiService | None = None) -> None:
        self.gemini = gemini_service or GeminiService()

    @staticmethod
    def is_duplicate_task(
        db: Session,
        user_id: int,
        title: str,
        deadline: datetime | None,
    ) -> bool:
        """Check if an identical or near-identical task already exists in active/pending state."""
        existing = (
            db.query(Task)
            .filter(
                Task.user_id == user_id,
                Task.status.in_(["pending", "in_progress"]),
                Task.title.ilike(title.strip()),
            )
            .first()
        )
        return existing is not None

    @staticmethod
    def get_context_snapshot(db: Session, user_id: int) -> dict[str, Any]:
        """Read-only context snapshot for the Orchestrator. No writes."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        # Pending tasks
        pending_tasks = (
            db.query(Task)
            .filter(Task.user_id == user_id, Task.status.in_(["pending", "in_progress"]))
            .order_by(Task.deadline.asc().nullslast())
            .limit(10)
            .all()
        )
        pending_tasks_data = [
            {
                "id": t.id,
                "title": t.title,
                "deadline": t.deadline.isoformat() if t.deadline else None,
                "priority": t.priority,
                "category": t.category,
            }
            for t in pending_tasks
        ]

        # Recent emails (last 5)
        recent_emails = (
            db.query(EmailMessage)
            .filter(EmailMessage.user_id == user_id)
            .order_by(EmailMessage.id.desc())
            .limit(5)
            .all()
        )
        recent_emails_data = [
            {"id": e.id, "subject": e.subject, "sender": e.sender, "processing_status": e.processing_status}
            for e in recent_emails
        ]

        # Upcoming deadlines (tasks with deadline in next 7 days)
        from datetime import timedelta
        deadline_cutoff = now + timedelta(days=7)
        upcoming_deadlines = [
            t for t in pending_tasks
            if t.deadline and t.deadline.replace(tzinfo=timezone.utc) <= deadline_cutoff
        ]
        upcoming_deadlines_data = [
            {"title": t.title, "deadline": t.deadline.isoformat(), "priority": t.priority}
            for t in upcoming_deadlines
        ]

        # Conflict windows for upcoming deadlines
        conflict_windows_data = []
        for t in upcoming_deadlines:
            if t.deadline:
                conflicts = InboxService.detect_conflicts_for_deadline(db, user_id, t.deadline)
                if conflicts:
                    conflict_windows_data.append({"task": t.title, "conflicts": conflicts})

        return {
            "pending_tasks": pending_tasks_data,
            "recent_emails": recent_emails_data,
            "upcoming_deadlines": upcoming_deadlines_data,
            "conflict_windows": conflict_windows_data,
        }

    @staticmethod
    def detect_conflicts_for_deadline(
        db: Session,
        user_id: int,
        due_at: datetime,
    ) -> list[dict[str, Any]]:
        """Check if a deadline falls inside any scheduled busy calendar event."""
        conflicts = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.user_id == user_id,
                CalendarEvent.starts_at <= due_at,
                CalendarEvent.ends_at >= due_at,
            )
            .all()
        )
        return [
            {
                "id": c.id,
                "title": c.title,
                "starts_at": c.starts_at.isoformat(),
                "ends_at": c.ends_at.isoformat(),
            }
            for c in conflicts
        ]

    async def process_content(
        self,
        db: Session,
        user_id: int,
        content: str,
        source_type: str = "email",
        source_metadata: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        workflow_id = f"inbox-proc-{uuid.uuid4().hex[:8]}"

        # 1. Extract structured tasks and deadlines using Gemini
        extraction = await self.gemini.extract_tasks_and_deadlines(
            content=content,
            source_type=source_type,
        )

        # Save email record to database
        if not dry_run and source_type == "email" and source_metadata and source_metadata.get("email_id"):
            gmail_id = str(source_metadata["email_id"])
            existing_email = db.query(EmailMessage).filter(EmailMessage.user_id == user_id, EmailMessage.gmail_id == gmail_id).first()
            if not existing_email:
                new_email = EmailMessage(
                    user_id=user_id,
                    gmail_id=gmail_id,
                    sender=source_metadata.get("from", "Unknown"),
                    subject=source_metadata.get("subject", "No Subject"),
                    snippet=content[:300],
                    body=content,
                    has_tasks_extracted=bool(extraction.tasks),
                )
                db.add(new_email)
                db.commit()

        created_tasks: list[dict[str, Any]] = []
        skipped_duplicates: list[str] = []
        detected_conflicts: list[dict[str, Any]] = []

        # 2. Process extracted tasks
        for item in extraction.tasks:
            if item.confidence < 0.6:
                continue

            if self.is_duplicate_task(db, user_id, item.title, item.deadline):
                skipped_duplicates.append(item.title)
                continue

            # Check calendar conflict if task has a deadline
            if item.deadline:
                conflicts = self.detect_conflicts_for_deadline(db, user_id, item.deadline)
                if conflicts:
                    detected_conflicts.append({
                        "task_title": item.title,
                        "deadline": item.deadline.isoformat(),
                        "conflicts": conflicts,
                    })

            if not dry_run:
                new_task = Task(
                    user_id=user_id,
                    title=item.title,
                    description=item.description,
                    deadline=item.deadline,
                    priority=item.priority,
                    category=item.category or "academic",
                    estimated_effort_hours=item.estimated_effort_hours,
                    source=source_type,
                )
                db.add(new_task)
                db.commit()
                db.refresh(new_task)

                if item.deadline:
                    new_deadline = Deadline(
                        user_id=user_id,
                        task_id=new_task.id,
                        title=item.title,
                        due_at=item.deadline,
                        source=source_type,
                        is_confirmed=True,
                    )
                    db.add(new_deadline)
                    db.commit()

                created_tasks.append({
                    "id": new_task.id,
                    "title": new_task.title,
                    "deadline": new_task.deadline.isoformat() if new_task.deadline else None,
                    "priority": new_task.priority,
                    "category": new_task.category,
                })
            else:
                created_tasks.append({
                    "id": None,
                    "title": item.title,
                    "deadline": item.deadline.isoformat() if item.deadline else None,
                    "priority": item.priority,
                    "category": item.category,
                })

        # 3. Log activity
        if not dry_run:
            AuditService.log_agent_action(
                db=db,
                user_id=user_id,
                tool_name="inbox_to_task_pipeline",
                status="success",
                workflow_id=workflow_id,
                input_params={"source_type": source_type, "content_len": len(content)},
                output_result={"tasks_created": len(created_tasks), "duplicates": len(skipped_duplicates)},
            )
            AuditService.log_user_activity(
                db=db,
                user_id=user_id,
                activity_type="inbox_processed",
                message=f"Extracted {len(created_tasks)} tasks from {source_type}",
                metadata={"tasks_created": len(created_tasks), "skipped_duplicates": len(skipped_duplicates)},
            )

        return {
            "workflow_id": workflow_id,
            "status": "completed",
            "summary": extraction.summary,
            "total_extracted": len(extraction.tasks),
            "tasks_created": created_tasks,
            "skipped_duplicates": skipped_duplicates,
            "detected_conflicts": detected_conflicts,
            "dry_run": dry_run,
        }
