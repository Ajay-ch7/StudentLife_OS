import logging
import re
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.telegram_adapter import TelegramAdapter
from app.models.calendar_event import CalendarEvent
from app.models.deadline import Deadline
from app.models.email_message import EmailMessage
from app.models.opportunity import Opportunity
from app.models.student_profile import User
from app.models.task import Task
from app.schemas.email_workflow_schemas import NormalizedEmail
from app.services.audit_service import AuditService
from app.services.inbox_service import InboxService
from app.services.orchestrator import multi_agent_orchestrator
from app.schemas.orchestration_schemas import OrchestratorEvent, OrchestratorEventType
from openclaw.agent.student_life_agent import StudentLifeAgent
from openclaw.workflows.base_workflow import BaseWorkflow

logger = logging.getLogger(__name__)


def extract_email_address(raw_sender: str) -> str | None:
    """Extract plain email address from sender string like 'Prof <prof@univ.edu>'."""
    match = re.search(r"<([^>]+)>", raw_sender)
    if match:
        return match.group(1).strip()
    if "@" in raw_sender:
        return raw_sender.strip()
    return None


class EmailToActionWorkflow(BaseWorkflow):
    """
    Autonomous OpenClaw workflow that automatically transforms newly arrived emails
    into validated tasks, updated deadlines, calendar events, drafts, and Telegram notifications.
    """

    def __init__(
        self,
        agent: StudentLifeAgent | None = None,
        telegram_adapter: TelegramAdapter | None = None,
    ) -> None:
        super().__init__(name="email_to_action", agent=agent)
        self.settings = get_settings()
        self.telegram = telegram_adapter or TelegramAdapter(self.settings)

    async def run(
        self,
        user_id: int,
        db: Session,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = payload or {}
        workflow_id = self.generate_workflow_id()

        # -----------------------------------------------------------------
        # 1. Extraction & Deduplication Check
        # -----------------------------------------------------------------
        message_id = str(payload.get("message_id") or payload.get("id") or "").strip()
        if not message_id:
            message_id = f"email-wf-{workflow_id}"

        # Prevent duplicate processing: verify if already processing or processed
        existing_email = (
            db.query(EmailMessage)
            .filter(EmailMessage.user_id == user_id, EmailMessage.gmail_id == message_id)
            .first()
        )

        if existing_email and existing_email.processing_status in ("processed", "processing"):
            logger.info(
                "Email %s already in status '%s'; skipping duplicate execution.",
                message_id,
                existing_email.processing_status,
            )
            return {
                "workflow_id": workflow_id,
                "status": "skipped",
                "reason": f"already_{existing_email.processing_status}",
                "message_id": message_id,
            }

        # Initialize or update EmailMessage record with 'processing' status
        raw_sender = str(payload.get("from") or payload.get("sender") or "Unknown")
        raw_subject = str(payload.get("subject") or "No Subject")
        raw_body = str(payload.get("body") or payload.get("snippet") or payload.get("content") or "")
        raw_date = str(payload.get("date") or payload.get("timestamp") or "")

        if not existing_email:
            existing_email = EmailMessage(
                user_id=user_id,
                gmail_id=message_id,
                thread_id=payload.get("thread_id"),
                sender=raw_sender[:250],
                subject=raw_subject[:500],
                snippet=raw_body[:300],
                body=raw_body,
                date_str=raw_date[:100],
                category="general",
                processing_status="processing",
            )
            db.add(existing_email)
        else:
            existing_email.processing_status = "processing"
            if raw_body and not existing_email.body:
                existing_email.body = raw_body

        db.commit()
        db.refresh(existing_email)

        self.log_workflow_start(
            db=db,
            user_id=user_id,
            workflow_id=workflow_id,
            message=f"Autonomous Email-to-Action initiated for email: '{raw_subject}'",
        )

        # -----------------------------------------------------------------
        # 2. Normalize Email Object
        # -----------------------------------------------------------------
        normalized = NormalizedEmail(
            message_id=message_id,
            thread_id=existing_email.thread_id,
            sender=existing_email.sender,
            sender_email=extract_email_address(existing_email.sender),
            subject=existing_email.subject,
            timestamp=existing_email.date_str or datetime.now(timezone.utc).isoformat(),
            body=existing_email.body or "",
            attachments=payload.get("attachments") or [],
            metadata=payload.get("metadata") or {},
        )

        try:
            # -----------------------------------------------------------------
            # 2b. Orchestrator Intercept (cross-agent context before isolated LLM)
            # -----------------------------------------------------------------
            try:
                orch_event = OrchestratorEvent(
                    event_type=OrchestratorEventType.NEW_EMAIL,
                    user_id=user_id,
                    payload=normalized.model_dump(),
                    workflow_id=f"orch-email-{workflow_id}",
                )
                orch_result = await multi_agent_orchestrator.run(orch_event, db)
                if orch_result.status in ("executed", "pending_approval"):
                    # Orchestrator handled it — log and continue (don't skip, let isolated logic also run
                    # for data persistence safety, but note the orchestration outcome)
                    logger.info(
                        "Orchestrator result for email workflow %s: status=%s agents=%s",
                        workflow_id, orch_result.status, orch_result.agents_executed,
                    )
                    if orch_result.status == "pending_approval":
                        existing_email.processing_status = "pending_approval"
                        db.commit()
            except Exception as orch_exc:
                logger.warning("Orchestrator intercept failed (fallback to isolated): %s", orch_exc)

            # -----------------------------------------------------------------
            # 3. Context Retrieval & LLM Reasoning (isolated — always runs for safety)
            # -----------------------------------------------------------------
            user = db.query(User).filter(User.id == user_id).first()
            active_tasks = (
                db.query(Task)
                .filter(Task.user_id == user_id, Task.status == "pending")
                .order_by(Task.deadline.asc().nullslast())
                .all()
            )
            active_tasks_data = [
                {
                    "id": t.id,
                    "title": t.title,
                    "deadline": t.deadline.isoformat() if t.deadline else None,
                    "priority": t.priority,
                    "category": t.category,
                }
                for t in active_tasks
            ]

            calendar_events = (
                db.query(CalendarEvent)
                .filter(CalendarEvent.user_id == user_id)
                .order_by(CalendarEvent.starts_at.asc())
                .limit(10)
                .all()
            )
            calendar_events_data = [
                {
                    "id": e.id,
                    "title": e.title,
                    "starts_at": e.starts_at.isoformat(),
                    "ends_at": e.ends_at.isoformat(),
                }
                for e in calendar_events
            ]

            decision = await self.agent.gemini.reason_over_email(
                email_data=normalized.model_dump(),
                profile=user.profile if user else None,
                active_tasks=active_tasks_data,
                calendar_events=calendar_events_data,
            )

            # -----------------------------------------------------------------
            # 4. Database Updates & State Synchronization
            # -----------------------------------------------------------------
            changes_made: list[str] = []
            created_tasks_list: list[dict[str, Any]] = []
            updated_tasks_list: list[dict[str, Any]] = []
            created_events_list: list[dict[str, Any]] = []

            # 4a. Update existing tasks (e.g. deadline extension)
            for upd in decision.tasks_to_update:
                target_task = None
                if upd.existing_task_id:
                    target_task = (
                        db.query(Task)
                        .filter(Task.id == upd.existing_task_id, Task.user_id == user_id)
                        .first()
                    )

                if not target_task and upd.matching_title_query:
                    query_term = upd.matching_title_query.strip().lower()
                    for t in active_tasks:
                        if query_term in t.title.lower() or t.title.lower() in query_term:
                            target_task = t
                            break

                if target_task:
                    old_deadline = target_task.deadline
                    if upd.new_deadline:
                        target_task.deadline = upd.new_deadline
                        # Sync deadline record
                        dl_rec = (
                            db.query(Deadline)
                            .filter(Deadline.task_id == target_task.id, Deadline.user_id == user_id)
                            .first()
                        )
                        if dl_rec:
                            dl_rec.due_at = upd.new_deadline
                        else:
                            new_dl = Deadline(
                                user_id=user_id,
                                task_id=target_task.id,
                                title=target_task.title,
                                due_at=upd.new_deadline,
                                source="email",
                                is_confirmed=True,
                            )
                            db.add(new_dl)

                    if upd.new_priority:
                        target_task.priority = upd.new_priority
                    if upd.new_title:
                        target_task.title = upd.new_title

                    db.commit()
                    db.refresh(target_task)

                    dl_str = (
                        f" to {target_task.deadline.strftime('%b %d, %I:%M %p')}"
                        if target_task.deadline
                        else ""
                    )
                    changes_made.append(f"• Updated deadline for '{target_task.title}'{dl_str}")
                    updated_tasks_list.append({"id": target_task.id, "title": target_task.title})
                else:
                    # If target wasn't found, create as new task to ensure nothing is lost
                    new_task = Task(
                        user_id=user_id,
                        title=upd.new_title or upd.matching_title_query,
                        deadline=upd.new_deadline,
                        priority=upd.new_priority or decision.priority,
                        category="academic",
                        source="email",
                    )
                    db.add(new_task)
                    db.commit()
                    db.refresh(new_task)
                    if upd.new_deadline:
                        db.add(
                            Deadline(
                                user_id=user_id,
                                task_id=new_task.id,
                                title=new_task.title,
                                due_at=upd.new_deadline,
                                source="email",
                                is_confirmed=True,
                            )
                        )
                        db.commit()
                    changes_made.append(f"• Added task '{new_task.title}'")
                    created_tasks_list.append({"id": new_task.id, "title": new_task.title})

            # 4b. Create new tasks
            for new_t in decision.tasks_to_create:
                if new_t.confidence < 0.6:
                    continue

                # Check if exact/near title already exists in active tasks
                existing_t = (
                    db.query(Task)
                    .filter(
                        Task.user_id == user_id,
                        Task.status.in_(["pending", "in_progress"]),
                        Task.title.ilike(new_t.title.strip()),
                    )
                    .first()
                )

                if existing_t:
                    # Update deadline if email provided a new one
                    if new_t.deadline and existing_t.deadline != new_t.deadline:
                        existing_t.deadline = new_t.deadline
                        dl_rec = (
                            db.query(Deadline)
                            .filter(Deadline.task_id == existing_t.id, Deadline.user_id == user_id)
                            .first()
                        )
                        if dl_rec:
                            dl_rec.due_at = new_t.deadline
                        db.commit()
                        changes_made.append(f"• Updated deadline for existing task '{existing_t.title}'")
                else:
                    task_record = Task(
                        user_id=user_id,
                        title=new_t.title,
                        description=new_t.description,
                        deadline=new_t.deadline,
                        priority=new_t.priority,
                        category=new_t.category or "assignment",
                        estimated_effort_hours=new_t.estimated_effort_hours,
                        source="email",
                    )
                    db.add(task_record)
                    db.commit()
                    db.refresh(task_record)

                    if new_t.deadline:
                        deadline_record = Deadline(
                            user_id=user_id,
                            task_id=task_record.id,
                            title=task_record.title,
                            due_at=new_t.deadline,
                            source="email",
                            is_confirmed=True,
                        )
                        db.add(deadline_record)
                        db.commit()

                    changes_made.append(f"• Added assignment '{task_record.title}' to Tasks")
                    created_tasks_list.append({"id": task_record.id, "title": task_record.title})

            # 4c. Calendar Events Creation & Scheduling
            for ev in decision.events_to_create:
                existing_ev = (
                    db.query(CalendarEvent)
                    .filter(
                        CalendarEvent.user_id == user_id,
                        CalendarEvent.title == ev.title,
                        CalendarEvent.starts_at == ev.starts_at,
                    )
                    .first()
                )
                if not existing_ev:
                    event_record = CalendarEvent(
                        user_id=user_id,
                        title=ev.title,
                        description=ev.description,
                        starts_at=ev.starts_at,
                        ends_at=ev.ends_at,
                        location=ev.location,
                        event_type="academic",
                    )
                    db.add(event_record)
                    db.commit()
                    changes_made.append(f"• Scheduled calendar event '{ev.title}'")
                    created_events_list.append({"title": ev.title, "starts_at": ev.starts_at.isoformat()})

            # 4d. Check for Calendar & Task Conflicts
            for dl in decision.deadlines:
                if dl.due_at:
                    conflicts = InboxService.detect_conflicts_for_deadline(db, user_id, dl.due_at)
                    for c in conflicts:
                        conflict_desc = f"Detected conflict with existing task/event '{c['title']}'"
                        if not any(conflict_desc in cm for cm in changes_made):
                            changes_made.append(f"• {conflict_desc}")

            for conf in decision.detected_conflicts:
                if conf and not any(conf.lower() in cm.lower() for cm in changes_made):
                    changes_made.append(f"• {conf}")

            # 4e. Internship / Opportunity ingestion
            combined_text = f"{raw_subject} {raw_body}".lower()
            if any(kw in combined_text for kw in ["intern", "internship", "hiring", "job alert", "opening", "unstop"]):
                company = "Opportunity Alert"
                for comp in ["Microsoft", "Adobe", "Google", "Amazon", "Apple", "Meta", "Uber", "Goldman Sachs", "Cisco", "Oracle", "Unstop"]:
                    if comp.lower() in combined_text:
                        company = comp
                        break

                existing_opp = (
                    db.query(Opportunity)
                    .filter(Opportunity.user_id == user_id, Opportunity.title == raw_subject)
                    .first()
                )
                if not existing_opp:
                    opp = Opportunity(
                        user_id=user_id,
                        title=raw_subject[:250],
                        company=company,
                        description=raw_body[:500],
                        required_skills="Problem Solving, DSA, Computer Science",
                        source="email_alert",
                        match_score=85.0,
                    )
                    db.add(opp)
                    db.commit()
                    changes_made.append(f"• Added career opportunity from {company}")

            # -----------------------------------------------------------------
            # 5. Autonomous Action Execution (Drafting / Safety)
            # -----------------------------------------------------------------
            if decision.draft_response_needed and decision.draft_response:
                draft = decision.draft_response
                draft_resp = await self.agent.run_tool(
                    "create_email_draft",
                    {
                        "to": draft.to,
                        "subject": draft.subject,
                        "body": draft.body,
                        "thread_id": existing_email.thread_id,
                    },
                    user_id=user_id,
                    db=db,
                    workflow_id=workflow_id,
                )
                if draft_resp.get("status") == "success":
                    req_id = draft_resp.get("result", {}).get("approval_request_id")
                    changes_made.append(f"• Drafted email reply to {draft.to} (Approval Request #{req_id})")

            if not changes_made:
                changes_made.append("• Recorded email and determined no immediate task changes needed")

            # -----------------------------------------------------------------
            # 6. Update Email Record in SQLite
            # -----------------------------------------------------------------
            existing_email.processing_status = "processed"
            existing_email.priority = decision.priority
            existing_email.requires_action = decision.requires_action
            existing_email.action_type = decision.recommended_action
            existing_email.reasoning = decision.reasoning
            existing_email.processed_at = datetime.now(timezone.utc)
            existing_email.has_tasks_extracted = bool(created_tasks_list or updated_tasks_list)
            db.commit()

            # -----------------------------------------------------------------
            # 7. Proactive Telegram Notification
            # -----------------------------------------------------------------
            primary_deadline_str = "None detected"
            if decision.deadlines:
                first_dl = decision.deadlines[0]
                d_time_str = (
                    first_dl.due_at.strftime("%b %d, %I:%M %p")
                    if hasattr(first_dl.due_at, "strftime")
                    else str(first_dl.due_at)
                )
                primary_deadline_str = f"{first_dl.title} — {d_time_str}"
            elif decision.tasks_to_create and decision.tasks_to_create[0].deadline:
                dl_val = decision.tasks_to_create[0].deadline
                d_time_str = (
                    dl_val.strftime("%b %d, %I:%M %p")
                    if hasattr(dl_val, "strftime")
                    else str(dl_val)
                )
                primary_deadline_str = f"{decision.tasks_to_create[0].title} — {d_time_str}"

            changes_bullets = "\n".join(changes_made)

            telegram_text = (
                "📩 New email processed\n\n"
                f"Priority: {decision.priority.upper()}\n"
                f"Deadline: {primary_deadline_str}\n\n"
                "Changes made:\n"
                f"{changes_bullets}\n\n"
                "Reason:\n"
                f"{decision.reasoning}"
            )

            # Proactively send notification without requiring user interaction
            # Filter: only notify if the email is actionable, has deadlines/tasks, or has >= medium priority
            is_actionable = (
                decision.priority in ("medium", "high", "urgent")
                or decision.requires_action
                or bool(decision.deadlines)
                or bool(created_tasks_list)
                or bool(updated_tasks_list)
                or bool(created_events_list)
            )

            target_chat_id = self.settings.telegram_chat_id
            if target_chat_id and is_actionable:
                try:
                    await self.telegram.send_message(text=telegram_text, chat_id=target_chat_id)
                    logger.info("Proactive Telegram notification delivered to %s", target_chat_id)
                except Exception as tg_err:
                    logger.warning("Could not dispatch Telegram alert: %s", tg_err)
            else:
                logger.info(
                    "Email '%s' is non-actionable (priority=%s); saved to DB without Telegram alert.",
                    raw_subject,
                    decision.priority,
                )


            self.log_workflow_complete(
                db=db,
                user_id=user_id,
                workflow_id=workflow_id,
                message=f"Email processed successfully with priority {decision.priority.upper()}",
                metadata={
                    "priority": decision.priority,
                    "tasks_created": len(created_tasks_list),
                    "tasks_updated": len(updated_tasks_list),
                },
            )

            AuditService.log_agent_action(
                db=db,
                user_id=user_id,
                tool_name="email_to_action_pipeline",
                status="success",
                workflow_id=workflow_id,
                input_params={"message_id": message_id, "subject": raw_subject},
                output_result={
                    "priority": decision.priority,
                    "tasks_created": len(created_tasks_list),
                    "tasks_updated": len(updated_tasks_list),
                },
            )

            return {
                "workflow_id": workflow_id,
                "status": "completed",
                "message_id": message_id,
                "priority": decision.priority,
                "summary": decision.summary,
                "reasoning": decision.reasoning,
                "changes_made": changes_made,
                "created_tasks": created_tasks_list,
                "updated_tasks": updated_tasks_list,
            }

        except Exception as e:
            logger.error("Error in EmailToActionWorkflow: %s", e, exc_info=True)
            existing_email.processing_status = "failed"
            existing_email.error_message = str(e)
            db.commit()
            return {
                "workflow_id": workflow_id,
                "status": "failed",
                "message_id": message_id,
                "error": str(e),
            }
