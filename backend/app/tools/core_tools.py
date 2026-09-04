from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.telegram_adapter import TelegramAdapter
from app.models.activity_log import ActivityLog
from app.models.approval_request import ApprovalRequest
from app.models.calendar_event import CalendarEvent
from app.models.deadline import Deadline
from app.models.student_profile import StudentProfile, User
from app.models.task import Task
from app.schemas.tools import (
    AnalyzeOpportunityToolInput,
    AnalyzeSkillGapInput,
    CheckEligibilityInput,
    CreateApprovalRequestToolInput,
    CreateCalendarEventInput,
    CreateEmailDraftInput,
    CreateGoogleCalendarEventInput,
    CreateTaskInput,
    DetectConflictsInput,
    GenerateStudyPlanToolInput,
    GetCalendarInput,
    GetDeadlinesInput,
    GetDSAProgressInput,
    GetProfileInput,
    GetTasksInput,
    ListGmailMessagesInput,
    ParseDocumentInput,
    RescheduleEventInput,
    SearchKnowledgeInput,
    SearchOpportunitiesInput,
    ScanGmailInboxInput,
    SendEmailDraftInput,
    SendTelegramMessageToolInput,
    SyncGoogleCalendarInput,
    ToolAccessLevel,
    UpdateTaskInput,
)
from app.integrations.gmail_adapter import GmailAdapter
from app.integrations.google_calendar_adapter import GoogleCalendarAdapter
from app.services.audit_service import AuditService
from app.services.gemini_service import GeminiService
from app.services.inbox_service import InboxService
from app.services.permission_service import PermissionService
from app.tools.tool_registry import tool_registry

settings = get_settings()
gemini_service = GeminiService()
telegram_adapter = TelegramAdapter(settings)
google_calendar_adapter = GoogleCalendarAdapter()
gmail_adapter = GmailAdapter()


@tool_registry.register(
    name="get_student_profile",
    input_model=GetProfileInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Retrieve the current student's profile information including degree, college, skills, and goals.",
)
def get_student_profile(payload: GetProfileInput, user_id: int, db: Session) -> dict[str, Any]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.profile:
        return {"error": "Profile not found"}
    profile: StudentProfile = user.profile
    return {
        "user_id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "college": profile.college,
        "degree": profile.degree,
        "year": profile.year,
        "cgpa": profile.cgpa,
        "skills": [s.strip() for s in (profile.skills or "").split(",") if s.strip()],
        "target_roles": [r.strip() for r in (profile.target_roles or "").split(",") if r.strip()],
        "target_companies": [c.strip() for c in (profile.target_companies or "").split(",") if c.strip()],
        "available_study_hours": profile.available_study_hours,
    }


@tool_registry.register(
    name="get_tasks",
    input_model=GetTasksInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Retrieve current tasks for the student, optionally filtered by status or priority.",
)
def get_tasks(payload: GetTasksInput, user_id: int, db: Session) -> list[dict[str, Any]]:
    query = db.query(Task).filter(Task.user_id == user_id)
    if payload.status:
        query = query.filter(Task.status == payload.status)
    if payload.priority:
        query = query.filter(Task.priority == payload.priority)
    tasks = query.order_by(Task.deadline.asc(), Task.id.asc()).limit(payload.limit).all()
    return [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "deadline": t.deadline.isoformat() if t.deadline else None,
            "status": t.status,
            "priority": t.priority,
            "category": t.category,
            "estimated_effort_hours": t.estimated_effort_hours,
        }
        for t in tasks
    ]


@tool_registry.register(
    name="create_task",
    input_model=CreateTaskInput,
    access_level=ToolAccessLevel.WRITE_LOCAL,
    description="Create a new task in the student's task database.",
)
def create_task(payload: CreateTaskInput, user_id: int, db: Session) -> dict[str, Any]:
    task = Task(
        user_id=user_id,
        title=payload.title,
        description=payload.description,
        deadline=payload.deadline,
        priority=payload.priority,
        category=payload.category,
        estimated_effort_hours=payload.estimated_effort_hours,
        source=payload.source,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # If task has a deadline, also insert a deadline record
    if payload.deadline:
        deadline_rec = Deadline(
            user_id=user_id,
            task_id=task.id,
            title=payload.title,
            due_at=payload.deadline,
            source=payload.source,
            is_confirmed=True,
        )
        db.add(deadline_rec)
        db.commit()

    AuditService.log_user_activity(
        db=db,
        user_id=user_id,
        activity_type="task_created",
        message=f"Created task: {task.title}",
        metadata={"task_id": task.id, "deadline": str(task.deadline)},
    )
    return {"id": task.id, "title": task.title, "status": task.status, "deadline": str(task.deadline)}


@tool_registry.register(
    name="update_task",
    input_model=UpdateTaskInput,
    access_level=ToolAccessLevel.WRITE_LOCAL,
    description="Update an existing task's status, priority, description, or deadline.",
)
def update_task(payload: UpdateTaskInput, user_id: int, db: Session) -> dict[str, Any]:
    task = db.query(Task).filter(Task.id == payload.task_id, Task.user_id == user_id).first()
    if not task:
        raise ValueError(f"Task with ID {payload.task_id} not found.")

    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.deadline is not None:
        task.deadline = payload.deadline
    if payload.status is not None:
        task.status = payload.status
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.category is not None:
        task.category = payload.category

    db.commit()
    db.refresh(task)
    return {"id": task.id, "title": task.title, "status": task.status, "priority": task.priority}


@tool_registry.register(
    name="get_calendar",
    input_model=GetCalendarInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Retrieve calendar events and scheduled commitments.",
)
def get_calendar(payload: GetCalendarInput, user_id: int, db: Session) -> list[dict[str, Any]]:
    query = db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id)
    if payload.start_date:
        query = query.filter(CalendarEvent.starts_at >= payload.start_date)
    if payload.end_date:
        query = query.filter(CalendarEvent.ends_at <= payload.end_date)
    events = query.order_by(CalendarEvent.starts_at.asc()).limit(payload.limit).all()
    return [
        {
            "id": e.id,
            "title": e.title,
            "description": e.description,
            "starts_at": e.starts_at.isoformat(),
            "ends_at": e.ends_at.isoformat(),
            "event_type": e.event_type,
            "location": e.location,
        }
        for e in events
    ]


@tool_registry.register(
    name="create_calendar_event",
    input_model=CreateCalendarEventInput,
    access_level=ToolAccessLevel.WRITE_LOCAL,
    description="Add a new event or study block to the calendar.",
)
def create_calendar_event(payload: CreateCalendarEventInput, user_id: int, db: Session) -> dict[str, Any]:
    event = CalendarEvent(
        user_id=user_id,
        title=payload.title,
        description=payload.description,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        event_type=payload.event_type,
        location=payload.location,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {"id": event.id, "title": event.title, "starts_at": event.starts_at.isoformat(), "ends_at": event.ends_at.isoformat()}


@tool_registry.register(
    name="reschedule_event",
    input_model=RescheduleEventInput,
    access_level=ToolAccessLevel.EXTERNAL_OR_CONSEQUENTIAL,
    requires_approval=True,
    description="Reschedule an existing calendar event to a new time window (requires user approval).",
)
def reschedule_event(payload: RescheduleEventInput, user_id: int, db: Session) -> dict[str, Any]:
    event = db.query(CalendarEvent).filter(CalendarEvent.id == payload.event_id, CalendarEvent.user_id == user_id).first()
    if not event:
        raise ValueError(f"Calendar event {payload.event_id} not found.")

    old_time = f"{event.starts_at} -> {event.ends_at}"
    event.starts_at = payload.new_starts_at
    event.ends_at = payload.new_ends_at
    db.commit()
    db.refresh(event)

    AuditService.log_user_activity(
        db=db,
        user_id=user_id,
        activity_type="event_rescheduled",
        message=f"Rescheduled '{event.title}' to {event.starts_at.isoformat()}",
        metadata={"event_id": event.id, "old_time": old_time, "reason": payload.reason},
    )
    return {"id": event.id, "title": event.title, "starts_at": event.starts_at.isoformat(), "ends_at": event.ends_at.isoformat()}


@tool_registry.register(
    name="get_deadlines",
    input_model=GetDeadlinesInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Retrieve all tracked deadlines.",
)
def get_deadlines(payload: GetDeadlinesInput, user_id: int, db: Session) -> list[dict[str, Any]]:
    query = db.query(Deadline).filter(Deadline.user_id == user_id)
    if payload.upcoming_only:
        now = datetime.now(timezone.utc)
        query = query.filter(Deadline.due_at >= now)
    deadlines = query.order_by(Deadline.due_at.asc()).limit(payload.limit).all()
    return [
        {
            "id": d.id,
            "title": d.title,
            "due_at": d.due_at.isoformat(),
            "source": d.source,
            "is_confirmed": d.is_confirmed,
        }
        for d in deadlines
    ]


@tool_registry.register(
    name="detect_conflicts",
    input_model=DetectConflictsInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Check whether a proposed time range overlaps with existing calendar events.",
)
def detect_conflicts(payload: DetectConflictsInput, user_id: int, db: Session) -> dict[str, Any]:
    query = db.query(CalendarEvent).filter(
        CalendarEvent.user_id == user_id,
        CalendarEvent.starts_at < payload.proposed_ends_at,
        CalendarEvent.ends_at > payload.proposed_starts_at,
    )
    if payload.exclude_event_id:
        query = query.filter(CalendarEvent.id != payload.exclude_event_id)
    conflicts = query.all()
    return {
        "has_conflicts": len(conflicts) > 0,
        "conflict_count": len(conflicts),
        "conflicting_events": [
            {
                "id": c.id,
                "title": c.title,
                "starts_at": c.starts_at.isoformat(),
                "ends_at": c.ends_at.isoformat(),
            }
            for c in conflicts
        ],
    }


@tool_registry.register(
    name="search_opportunities",
    input_model=SearchOpportunitiesInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Search real stored internship and job listings by keyword.",
)
def search_opportunities(payload: SearchOpportunitiesInput, user_id: int, db: Session) -> list[dict[str, Any]]:
    from app.models.opportunity import Opportunity
    all_opps = db.query(Opportunity).filter(Opportunity.user_id == user_id).order_by(Opportunity.match_score.desc().nullslast(), Opportunity.id.desc()).all()
    
    if not all_opps:
        return []

    if payload.query and payload.query.strip():
        terms = [t.lower() for t in payload.query.strip().split() if len(t) > 2]
        matched = []
        for o in all_opps:
            haystack = f"{o.title} {o.company} {o.description} {o.required_skills or ''}".lower()
            if any(term in haystack for term in terms):
                matched.append(o)
        if matched:
            all_opps = matched

    return [
        {
            "id": o.id,
            "title": o.title,
            "company": o.company,
            "description": o.description,
            "required_skills": o.required_skills,
            "match_score": o.match_score,
            "url": o.url,
            "source": o.source,
        }
        for o in all_opps[: payload.limit]
    ]


@tool_registry.register(
    name="analyze_opportunity",
    input_model=AnalyzeOpportunityToolInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Analyze an internship or job posting against student skills using Gemini.",
)
async def analyze_opportunity(payload: AnalyzeOpportunityToolInput, user_id: int, db: Session) -> dict[str, Any]:
    user = db.query(User).filter(User.id == user_id).first()
    profile = user.profile if user else None
    analysis = await gemini_service.analyze_opportunity(profile=profile, job_description=payload.opportunity_text)
    return analysis.model_dump()


@tool_registry.register(
    name="check_eligibility",
    input_model=CheckEligibilityInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Check whether the student meets basic eligibility criteria (CGPA, degree, graduation year).",
)
def check_eligibility(payload: CheckEligibilityInput, user_id: int, db: Session) -> dict[str, Any]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.profile:
        return {"eligible": False, "reason": "Profile missing"}
    p = user.profile
    reasons: list[str] = []

    if payload.min_cgpa is not None and (p.cgpa or 0) < payload.min_cgpa:
        reasons.append(f"CGPA {p.cgpa} is below required minimum {payload.min_cgpa}")
    if payload.allowed_degrees and p.degree and p.degree not in payload.allowed_degrees:
        reasons.append(f"Degree '{p.degree}' not in eligible list {payload.allowed_degrees}")
    if payload.target_year is not None and p.year != payload.target_year:
        reasons.append(f"Year {p.year} does not match required year {payload.target_year}")

    return {
        "eligible": len(reasons) == 0,
        "cgpa": p.cgpa,
        "degree": p.degree,
        "year": p.year,
        "unmet_criteria": reasons,
    }


@tool_registry.register(
    name="analyze_skill_gap",
    input_model=AnalyzeSkillGapInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Compare a list of target skills against the student's current skill profile.",
)
def analyze_skill_gap(payload: AnalyzeSkillGapInput, user_id: int, db: Session) -> dict[str, Any]:
    user = db.query(User).filter(User.id == user_id).first()
    student_skills = set(
        s.strip().lower()
        for s in (user.profile.skills if user and user.profile and user.profile.skills else "").split(",")
        if s.strip()
    )
    target_skills = [s.strip() for s in payload.required_skills if s.strip()]
    matched = [s for s in target_skills if s.lower() in student_skills]
    missing = [s for s in target_skills if s.lower() not in student_skills]
    score = int((len(matched) / len(target_skills)) * 100) if target_skills else 100
    return {
        "matched_skills": matched,
        "missing_skills": missing,
        "match_percentage": score,
    }


@tool_registry.register(
    name="get_dsa_progress",
    input_model=GetDSAProgressInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Retrieve student's DSA progress, topic mastery, and suggested revision items.",
)
def get_dsa_progress(payload: GetDSAProgressInput, user_id: int, db: Session) -> dict[str, Any]:
    from app.models.dsa_problem import DSAProblem

    problems = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).all()
    if payload.topic:
        problems = [problem for problem in problems if payload.topic.lower() in problem.topic.lower()]
    grouped: dict[str, list[DSAProblem]] = {}
    for problem in problems:
        grouped.setdefault(problem.topic, []).append(problem)
    topics = [
        {
            "topic": topic,
            "solved": len(items),
            "confidence": "low" if sum(item.needs_revision for item in items) else "medium",
            "last_revised_days_ago": None,
        }
        for topic, items in sorted(grouped.items())
    ]
    return {
        "total_solved": len(problems),
        "topics": topics,
        "revision_needed": [t["topic"] for t in topics if t["confidence"] == "low"],
    }


@tool_registry.register(
    name="generate_study_plan",
    input_model=GenerateStudyPlanToolInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Generate a daily study plan for pending tasks and calendar openings using Gemini.",
)
async def generate_study_plan(payload: GenerateStudyPlanToolInput, user_id: int, db: Session) -> dict[str, Any]:
    user = db.query(User).filter(User.id == user_id).first()
    profile = user.profile if user else None
    tasks = db.query(Task).filter(Task.user_id == user_id, Task.status == "pending").all()
    events = db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id).all()
    
    tasks_data = [{"title": t.title, "priority": t.priority, "category": t.category} for t in tasks]
    events_data = [{"title": e.title, "starts_at": e.starts_at.isoformat(), "ends_at": e.ends_at.isoformat()} for e in events]
    
    plan = await gemini_service.generate_study_plan(profile=profile, tasks=tasks_data, calendar_events=events_data)
    return plan.model_dump()


@tool_registry.register(
    name="parse_document",
    input_model=ParseDocumentInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Read and parse a text or syllabus file from the local data/uploads folder.",
)
def parse_document(payload: ParseDocumentInput, user_id: int, db: Session) -> dict[str, Any]:
    safe_path = PermissionService.validate_file_path(payload.file_path)
    if not safe_path.exists():
        raise FileNotFoundError(f"File not found: {payload.file_path}")
    text_content = safe_path.read_text(encoding="utf-8", errors="replace")
    return {
        "file_name": safe_path.name,
        "char_count": len(text_content),
        "content_snippet": text_content[:2000],
    }


@tool_registry.register(
    name="search_student_knowledge",
    input_model=SearchKnowledgeInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Search through stored student notes, logs, and summaries.",
)
def search_student_knowledge(payload: SearchKnowledgeInput, user_id: int, db: Session) -> list[dict[str, Any]]:
    query_str = f"%{payload.query}%"
    logs = db.query(ActivityLog).filter(
        ActivityLog.user_id == user_id,
        ActivityLog.message.ilike(query_str),
    ).limit(payload.limit).all()
    return [{"id": l.id, "type": l.activity_type, "message": l.message, "date": str(l.created_at)} for l in logs]


@tool_registry.register(
    name="send_telegram_message",
    input_model=SendTelegramMessageToolInput,
    access_level=ToolAccessLevel.EXTERNAL_OR_CONSEQUENTIAL,
    requires_approval=True,
    description="Send a notification or morning briefing to the student via Telegram (requires user approval).",
)
async def send_telegram_message(payload: SendTelegramMessageToolInput, user_id: int, db: Session) -> dict[str, Any]:
    msg = await telegram_adapter.send_message(text=payload.text, chat_id=payload.chat_id)
    AuditService.log_user_activity(
        db=db,
        user_id=user_id,
        activity_type="telegram_sent",
        message=f"Sent notification: {payload.text[:50]}...",
        metadata={"mocked": msg.mocked, "chat_id": msg.chat_id},
    )
    return {"status": "sent", "mocked": msg.mocked, "chat_id": msg.chat_id}


@tool_registry.register(
    name="create_approval_request",
    input_model=CreateApprovalRequestToolInput,
    access_level=ToolAccessLevel.WRITE_LOCAL,
    description="Create a pending approval request for the student to approve high-impact actions.",
)
def create_approval_request(payload: CreateApprovalRequestToolInput, user_id: int, db: Session) -> dict[str, Any]:
    from app.services.approval_service import ApprovalService

    req = ApprovalService.create(
        db=db,
        user_id=user_id,
        action_type=payload.action_type,
        description=payload.description,
        metadata_json=payload.metadata_json,
    )
    return {"id": req.id, "action_type": req.action_type, "status": req.status}


@tool_registry.register(
    name="sync_google_calendar",
    input_model=SyncGoogleCalendarInput,
    access_level=ToolAccessLevel.WRITE_LOCAL,
    description="Sync events from the user's primary Google Calendar into the local schedule database.",
)
def sync_google_calendar(payload: SyncGoogleCalendarInput, user_id: int, db: Session) -> dict[str, Any]:
    res = google_calendar_adapter.sync_to_local_db(db, user_id, days_ahead=payload.days_ahead)
    AuditService.log_user_activity(
        db=db,
        user_id=user_id,
        activity_type="google_calendar_synced",
        message=f"Synced {res.get('synced_count', 0)} events from Google Calendar",
        metadata=res,
    )
    return res


@tool_registry.register(
    name="create_google_calendar_event",
    input_model=CreateGoogleCalendarEventInput,
    access_level=ToolAccessLevel.EXTERNAL_ACTION,
    description="Create a new event on Google Calendar and add it to the local schedule.",
)
def create_google_calendar_event(payload: CreateGoogleCalendarEventInput, user_id: int, db: Session) -> dict[str, Any]:
    # 1. Insert into Google Calendar
    google_res = google_calendar_adapter.create_event(
        title=payload.title,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        description=payload.description or "",
        location=payload.location or "",
    )
    # 2. Also record locally in SQLite
    local_event = CalendarEvent(
        user_id=user_id,
        google_event_id=google_res.get("google_id"),
        title=payload.title,
        description=payload.description,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        location=payload.location,
        event_type="commitment",
        creation_notified=True,
    )
    db.add(local_event)
    db.commit()
    db.refresh(local_event)

    return {
        "local_event_id": local_event.id,
        "google_result": google_res,
        "status": "success",
    }


@tool_registry.register(
    name="list_gmail_messages",
    input_model=ListGmailMessagesInput,
    access_level=ToolAccessLevel.READ_LOCAL,
    description="Fetch recent email messages or announcements from Gmail.",
)
def list_gmail_messages(payload: ListGmailMessagesInput, user_id: int, db: Session) -> list[dict[str, Any]]:
    return gmail_adapter.list_recent_messages(query=payload.query, max_results=payload.max_results)


@tool_registry.register(
    name="create_email_draft",
    input_model=CreateEmailDraftInput,
    access_level=ToolAccessLevel.EXTERNAL_ACTION,
    description="Create an email draft in Gmail and generate an approval request for sending it.",
)
def create_email_draft(payload: CreateEmailDraftInput, user_id: int, db: Session) -> dict[str, Any]:
    from app.services.approval_service import ApprovalService

    draft_res = gmail_adapter.create_draft(
        to=payload.to,
        subject=payload.subject,
        body_text=payload.body,
        thread_id=payload.thread_id,
    )
    if draft_res.get("status") == "success":
        draft_id = draft_res.get("draft_id")
        # Automatically record an approval request so human must approve sending
        req = ApprovalService.create(
            db=db,
            user_id=user_id,
            action_type="send_email_draft",
            description=f"Send drafted email to {payload.to} with subject '{payload.subject}'",
            metadata_json=json.dumps({"draft_id": draft_id, "to": payload.to, "subject": payload.subject}),
        )
        draft_res["approval_request_id"] = req.id
        draft_res["requires_approval"] = True
    return draft_res


@tool_registry.register(
    name="send_email_draft",
    input_model=SendEmailDraftInput,
    access_level=ToolAccessLevel.EXTERNAL_OR_CONSEQUENTIAL,
    requires_approval=True,
    description="Send a previously drafted Gmail message (strictly requires user approval).",
)
def send_email_draft(payload: SendEmailDraftInput, user_id: int, db: Session) -> dict[str, Any]:
    send_res = gmail_adapter.send_draft(draft_id=payload.draft_id)
    AuditService.log_user_activity(
        db=db,
        user_id=user_id,
        activity_type="email_draft_sent",
        message=f"Dispatched Gmail draft {payload.draft_id}",
        metadata=send_res,
    )
    return send_res


@tool_registry.register(
    name="scan_gmail_inbox",
    input_model=ScanGmailInboxInput,
    access_level=ToolAccessLevel.WRITE_LOCAL,
    description="Scan recent Gmail messages, analyze content for assignments, exams, and opportunities using Gemini, and create tasks/deadlines.",
)
async def scan_gmail_inbox(payload: ScanGmailInboxInput, user_id: int, db: Session) -> dict[str, Any]:
    inbox_service = InboxService(gemini_service)
    messages = gmail_adapter.list_recent_messages(query=payload.query, max_results=payload.max_results)
    
    if not messages:
        return {
            "status": "success",
            "messages_scanned": 0,
            "tasks_created": [],
            "message": "No emails found matching query.",
        }

    all_created_tasks = []
    scanned_summaries = []

    for msg in messages:
        content = f"From: {msg.get('from')}\nSubject: {msg.get('subject')}\nDate: {msg.get('date')}\n\n{msg.get('body') or msg.get('snippet', '')}"
        res = await inbox_service.process_content(
            db=db,
            user_id=user_id,
            content=content,
            source_type="email",
            source_metadata={"email_id": msg.get("id"), "subject": msg.get("subject"), "from": msg.get("from")},
            dry_run=payload.dry_run,
        )
        scanned_summaries.append({
            "subject": msg.get("subject"),
            "from": msg.get("from"),
            "tasks_extracted": res.get("total_extracted", 0),
        })
        all_created_tasks.extend(res.get("tasks_created", []))

    return {
        "status": "success",
        "messages_scanned": len(messages),
        "tasks_created": all_created_tasks,
        "scanned_emails": scanned_summaries,
    }

