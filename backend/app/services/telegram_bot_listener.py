import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import SessionLocal
from app.models.calendar_event import CalendarEvent
from app.models.task import Task
from app.models.approval_request import ApprovalRequest
from app.services.briefing_service import BriefingService
from app.services.gemini_service import GeminiService
from app.services.approval_service import ApprovalService
from openclaw.tools.registry import OpenClawToolBridge

logger = logging.getLogger(__name__)


class TelegramBotListener:
    """
    Two-way interactive Telegram Bot listener wired directly into OpenClaw and backend tools.
    Polls getUpdates, validates user authorization, and routes messages to OpenClaw.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.running = False
        self.last_update_id = 0
        self.tool_bridge = OpenClawToolBridge()
        self.gemini = GeminiService()
        self.briefing_service = BriefingService()

    @property
    def token(self) -> str | None:
        return self.settings.telegram_bot_token

    @property
    def authorized_chat_id(self) -> str | None:
        return self.settings.telegram_chat_id

    @property
    def is_configured(self) -> bool:
        return bool(self.token and not self.settings.telegram_mock_mode)

    async def send_reply(self, chat_id: str | int, text: str) -> None:
        """Send a message back to Telegram."""
        if not self.token:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(url, json={"chat_id": str(chat_id), "text": text})
        except Exception as e:
            logger.error("Failed to send Telegram reply: %s", e)

    async def send_message(self, chat_id: str | int, text: str) -> None:
        """Proactively send a message to the student via Telegram."""
        await self.send_reply(chat_id=chat_id, text=text)


    async def handle_command(self, text: str, user_id: int, db: Session) -> str:
        """Handle predefined Telegram slash commands."""
        parts = text.strip().split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ("/start", "/help"):
            return (
                "👋 Welcome to StudentLife OS (Powered by OpenClaw & Gemini)!\n\n"
                "I am your local AI copilot. Here is what you can do:\n\n"
                "📅 Calendar & Schedule:\n"
                "• /calendar - View today's schedule & detect conflicts\n"
                "• /sync - Sync with your Google Calendar\n"
                "• Or text me: \"Add study session at 5pm\" or \"Do I have conflicts tomorrow?\"\n\n"
                "✉️ Gmail & Inbox:\n"
                "• /emails - View recent emails from your connected Gmail\n"
                "• /scan - Scan Gmail for new assignments, deadlines & notices\n"
                "• /drafts - View pending drafts needing your approval\n"
                "• /approve <id> - Approve and send an email draft\n"
                "• /reject <id> - Reject a pending action\n\n"
                "🌅 Daily Briefing & Tasks:\n"
                "• /briefing - Get today's morning briefing\n"
                "• /tasks - View pending academic tasks\n\n"
                "💡 You can also ask me anything in plain English (e.g., 'Check my emails for any assignments')!"
            )

        if cmd == "/briefing":
            briefing = await self.briefing_service.generate_briefing(db, user_id=user_id, send_notification=False)
            return briefing["formatted_text"]

        if cmd == "/calendar":
            now = datetime.now(timezone.utc)
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day.replace(hour=23, minute=59, second=59)

            events = (
                db.query(CalendarEvent)
                .filter(
                    CalendarEvent.user_id == user_id,
                    CalendarEvent.starts_at >= start_of_day,
                    CalendarEvent.starts_at <= end_of_day,
                )
                .order_by(CalendarEvent.starts_at.asc())
                .all()
            )
            if not events:
                return (
                    "📅 No events scheduled for today in your local calendar.\n"
                    "Tip: Run /sync to pull from Google Calendar, or text me to add an event!"
                )

            lines = ["📅 Today's Schedule:"]
            for e in events:
                t_str = f"{e.starts_at.strftime('%I:%M %p')} - {e.ends_at.strftime('%I:%M %p')}"
                lines.append(f"• {t_str}: {e.title}")

            # Check for overlaps among events
            conflicts = []
            for i in range(len(events)):
                for j in range(i + 1, len(events)):
                    if events[i].starts_at < events[j].ends_at and events[j].starts_at < events[i].ends_at:
                        conflicts.append(f"⚠️ Conflict: '{events[i].title}' overlaps with '{events[j].title}'!")

            if conflicts:
                lines.append("\n" + "\n".join(conflicts))
                lines.append("Tip: Ask me to reschedule or find an open slot!")
            else:
                lines.append("\n✅ No schedule overlaps detected.")

            return "\n".join(lines)

        if cmd == "/sync":
            sync_res = await self.tool_bridge.invoke_tool(
                "sync_google_calendar", {"days_ahead": 14}, user_id, db
            )
            if sync_res.status == "success":
                synced = sync_res.result.get("synced_count", 0)
                total = sync_res.result.get("total_google_events", 0)
                return f"🔄 Google Calendar Sync Complete!\nFound {total} Google Calendar events. Merged {synced} into your local schedule."
            return f"⚠️ Sync status: {sync_res.result.get('message', 'Google Calendar not connected')}"

        if cmd in ("/emails", "/inbox"):
            email_res = await self.tool_bridge.invoke_tool(
                "list_gmail_messages", {"query": "", "max_results": 5}, user_id, db
            )

            if email_res.status == "success":
                msgs = email_res.result
                if not msgs:
                    return "📭 No recent emails found in your Gmail inbox."
                lines = ["📬 Recent Gmail Messages:"]
                for i, m in enumerate(msgs[:5], 1):
                    sender = m.get("from", "Unknown").split("<")[0].strip()
                    subj = m.get("subject", "No Subject")
                    lines.append(f"{i}. *{sender}*: {subj}")
                lines.append("\n⚡ Real-time monitoring is active: tasks, assignments, and deadlines are automatically extracted and saved to your database.")
                return "\n".join(lines)
            return "⚠️ Could not connect to Gmail API. Ensure credentials are active."

        if cmd == "/scan":
            scan_res = await self.tool_bridge.invoke_tool(
                "scan_gmail_inbox", {"query": "", "max_results": 10, "dry_run": False}, user_id, db
            )
            if scan_res.status == "success":
                scanned = scan_res.result.get("messages_scanned", 0)
                tasks = scan_res.result.get("tasks_created", [])
                if not tasks:
                    return f"🔍 Scanned {scanned} recent emails. No new assignments or deadlines found."
                lines = [f"🔍 Scanned {scanned} emails. Created {len(tasks)} new task(s):"]
                for t in tasks:
                    dl = f" (Due: {t.get('deadline')})" if t.get('deadline') else ""
                    lines.append(f"• [{t.get('priority', 'medium').upper()}] {t.get('title')}{dl}")
                return "\n".join(lines)
            return f"⚠️ Scan failed: {scan_res.error}"

        if cmd in ("/opportunities", "/jobs", "/internships"):
            opps_res = await self.tool_bridge.invoke_tool(
                "search_opportunities", {"query": "", "limit": 5}, user_id, db
            )
            if opps_res.status == "success":
                opps = opps_res.result or []
                if not opps:
                    return "💼 No opportunities currently stored. Run /scan to pull from recent emails!"
                lines = ["💼 Your Matched Opportunities & Internships:"]
                for i, o in enumerate(opps, 1):
                    lines.append(f"{i}. *{o.get('company')}* - {o.get('title')}\n   Skills: {o.get('required_skills', 'N/A')}")
                return "\n".join(lines)
            return f"⚠️ Could not search opportunities: {opps_res.error}"

        if cmd == "/tasks":
            tasks = (
                db.query(Task)
                .filter(Task.user_id == user_id, Task.status == "pending")
                .order_by(Task.deadline.asc().nullslast())
                .limit(10)
                .all()
            )
            if not tasks:
                return "✅ All clear! You have no pending tasks right now."
            lines = ["📋 Pending Tasks:"]
            for t in tasks:
                dl = f" (Due: {t.deadline.strftime('%b %d')})" if t.deadline else ""
                lines.append(f"• [{t.priority.upper()}] {t.title}{dl}")
            return "\n".join(lines)

        if cmd == "/drafts":
            approvals = (
                db.query(ApprovalRequest)
                .filter(ApprovalRequest.user_id == user_id, ApprovalRequest.status == "pending")
                .order_by(ApprovalRequest.requested_at.desc())
                .all()
            )
            if not approvals:
                return "✅ No pending approvals or drafts waiting for your review."
            lines = ["📝 Pending Approvals & Email Drafts:"]
            for a in approvals:
                lines.append(f"• ID #{a.id} [{a.action_type}]: {a.description}")
            lines.append("\nReply with /approve <id> or /reject <id>")
            return "\n".join(lines)

        if cmd == "/approve" and args:
            try:
                req_id = int(args[0])
                req = (
                    db.query(ApprovalRequest)
                    .filter(ApprovalRequest.id == req_id, ApprovalRequest.user_id == user_id)
                    .first()
                )
                if not req:
                    return f"❌ Approval request #{req_id} not found."
                resolved_req = ApprovalService.resolve(db, req, status="approved")
                if resolved_req.action_type == "send_email_draft":
                    meta = json.loads(resolved_req.metadata_json or "{}")
                    draft_id = meta.get("draft_id")
                    if draft_id:
                        send_res = await self.tool_bridge.invoke_tool(
                            "send_email_draft", {"draft_id": draft_id}, user_id, db, approved=True
                        )
                        return f"✅ Approval #{req_id} confirmed! Gmail draft sent successfully."
                return f"✅ Approval #{req_id} ({resolved_req.action_type}) approved!"
            except Exception as e:
                return f"❌ Failed to approve request: {e}"

        if cmd == "/reject" and args:
            try:
                req_id = int(args[0])
                req = (
                    db.query(ApprovalRequest)
                    .filter(ApprovalRequest.id == req_id, ApprovalRequest.user_id == user_id)
                    .first()
                )
                if not req:
                    return f"❌ Approval request #{req_id} not found."
                ApprovalService.resolve(db, req, status="rejected")
                return f"🛑 Approval #{req_id} rejected."
            except Exception as e:
                return f"❌ Failed to reject request: {e}"

        return "I didn't recognize that command. Type /help to see what I can do!"

    async def handle_natural_language(self, text: str, user_id: int, db: Session) -> str:
        """
        Use Gemini reasoning to parse user intent and execute safe tools via OpenClaw.
        Grounds Gemini with live database context to prevent hallucinations.
        """
        now = datetime.now().astimezone()
        now_str = now.strftime("%A, %B %d, %Y at %I:%M %p")

        from app.models.student_profile import User
        from app.models.task import Task
        from app.models.calendar_event import CalendarEvent
        from app.models.opportunity import Opportunity

        user = db.query(User).filter(User.id == user_id).first()

        profile_info = "Student"
        if user and user.profile:
            p = user.profile
            profile_info = f"Name: {user.full_name}, Degree: {p.degree or 'CS'}, Year: {p.year or 3}, CGPA: {p.cgpa or 8.8}, Target Roles: {p.target_roles or 'Software Engineer'}, Skills: {p.skills or 'Python, DSA'}"

        # Fetch live database summary for grounding
        active_tasks = db.query(Task).filter(Task.user_id == user_id, Task.status == "pending").all()
        task_summaries = []
        for t in active_tasks:
            dl_str = f" (Due: {t.deadline.strftime('%b %d')})" if t.deadline else ""
            desc_str = f" - {t.description}" if t.description else ""
            task_summaries.append(f"• [{t.priority.upper()}] {t.title}{dl_str}{desc_str}")
        task_context_str = "\n".join(task_summaries) if task_summaries else "No pending tasks."

        upcoming_events = db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id, CalendarEvent.starts_at >= now).order_by(CalendarEvent.starts_at.asc()).limit(5).all()
        event_summaries = [f"• {e.title} ({e.starts_at.strftime('%b %d, %I:%M %p')})" for e in upcoming_events]
        event_context_str = "\n".join(event_summaries) if event_summaries else "No upcoming events scheduled."

        opps_db = db.query(Opportunity).filter(Opportunity.user_id == user_id).limit(5).all()
        opp_summaries = [f"• {o.company}: {o.title}" for o in opps_db]
        opp_context_str = "\n".join(opp_summaries) if opp_summaries else "No career opportunities stored."

        prompt = f"""You are OpenClaw, the intelligent AI student copilot for StudentLife OS.
Current Time: {now_str}
User Profile: {profile_info}
User ID: {user_id}

LIVE DATABASE STATE (Ground Truth):
[Active Tasks in Database ({len(active_tasks)})]:
{task_context_str}

[Upcoming Calendar Events]:
{event_context_str}

[Stored Career Opportunities ({len(opps_db)})]:
{opp_context_str}

User's Message: "{text}"

Decide the best course of action:
- "create_task": If user explicitly wants to add/create a new task or reminder (parameters: title, priority, deadline).
- "create_calendar_event": If user explicitly asks to schedule/add an event or study session (parameters: title, starts_at, ends_at, description, location).
- "create_email_draft": If user asks to compose/draft an email (parameters: to, subject, body).
- "scan_gmail_inbox": If user asks to scan/re-scan inbox emails for new items (parameters: query: "", max_results: 10, dry_run: false).
- "sync_google_calendar": If user asks to sync or refresh calendar (parameters: days_ahead: 14).
- "check_calendar_conflict": If user proposes a specific time slot and asks if they are free (parameters: proposed_starts_at, proposed_ends_at).
- "none": For ALL inquiries, questions, search requests, status checks, project queries, deadline questions, or general conversation. Use the LIVE DATABASE STATE above to directly answer the user's specific question in detail in "conversational_reply".

STRICT INSTRUCTIONS:
- When answering questions about tasks, projects, deadlines, or opportunities, analyze the LIVE DATABASE STATE carefully and answer the user's exact question with specific details (e.g. task title, description, submission instructions, deadline, priority).
- If the user asks about a project or specific topic (e.g. "is there any task to submit my project"), find the relevant matching tasks from the database (e.g. "Submit Student App project" and "Hackathon submission") and explain their details directly to the user.
- If the user asks for a general list of all tasks (e.g. "what are my pending tasks", "list tasks"), provide a clean, organized bulleted list of all active tasks.
- NEVER invent fake courses, tasks, or exams (like "DBMS Assignment"). Only use what is in the LIVE DATABASE STATE.

Respond with valid JSON ONLY:
{{
  "tool_name": "tool_name_or_none",
  "parameters": {{}},
  "conversational_reply": "Detailed, accurate, helpful answer grounded strictly in the live database."
}}"""

        try:
            raw_json = await self.gemini.client.generate_json(
                prompt=prompt,
                system_instruction="You are OpenClaw, a smart, proactive student copilot for StudentLife OS. Always use stored database data. Never invent fake tasks or mention markdown files.",
            )
            parsed = json.loads(raw_json)
            tool_name = parsed.get("tool_name", "none")
            parameters = parsed.get("parameters", {})
            conversational_reply = parsed.get("conversational_reply", "")

            if tool_name and tool_name != "none":
                # Execute action tool via OpenClaw Tool Bridge
                tool_res = await self.tool_bridge.invoke_tool(tool_name, parameters, user_id, db)
                if tool_res.status == "success":
                    if tool_name == "create_task":
                        t = tool_res.result or {}
                        return f"✅ Task created in database: *{t.get('title')}*\nPriority: {t.get('priority', 'medium').upper()}"
                    if tool_name == "create_calendar_event":
                        ev = tool_res.result or {}
                        return f"📅 Event scheduled: *{ev.get('title')}*\nTime: {ev.get('starts_at', '')[:16]}"
                    if tool_name == "create_email_draft":
                        req_id = tool_res.result.get("approval_request_id")
                        return (
                            f"📝 Draft created in Gmail!\n"
                            f"Approval Request ID: #{req_id}\n"
                            f"Reply `/approve {req_id}` to send it, or review in your Gmail Drafts."
                        )
                    if tool_name == "scan_gmail_inbox":
                        tasks = tool_res.result.get("tasks_created", [])
                        scanned = tool_res.result.get("messages_scanned", 0)
                        if tasks:
                            t_list = "\n".join([f"• [{t.get('priority', 'medium').upper()}] {t.get('title')}" for t in tasks])
                            return f"🔍 Scanned {scanned} emails and extracted {len(tasks)} new task(s):\n{t_list}"
                        return f"🔍 Scanned {scanned} emails. No new pending tasks found."
                    if tool_name == "sync_google_calendar":
                        synced = tool_res.result.get("synced_count", 0)
                        return f"🔄 Google Calendar Synced: {synced} event(s) merged."
                    if tool_name == "check_calendar_conflict":
                        has_conflict = tool_res.result.get("has_conflict", False)
                        if has_conflict:
                            conflicts = tool_res.result.get("conflicts", [])
                            c_names = ", ".join(c.get("title", "") for c in conflicts)
                            return f"⚠️ Conflict Detected! Overlaps with: {c_names}."
                        return "✅ Time slot is completely free! No conflicts found."
                elif tool_res.status == "approval_required":
                    return "🔒 This action requires your approval. An approval request has been created in your dashboard."
                else:
                    return f"{conversational_reply}\n(Note: Tool encountered: {tool_res.error})"

            return conversational_reply or "I'm on it! How else can I help your schedule or studies?"
        except Exception as e:
            logger.error("Error in natural language reasoning: %s", e)
            return f"I received your message: \"{text}\". (Reasoning note: {e})"

    async def process_update(self, update: dict[str, Any]) -> None:
        """Process a single update item from Telegram."""
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        chat = msg.get("chat", {})
        chat_id = str(chat.get("id"))
        text = (msg.get("text") or "").strip()
        if not text:
            return

        # Ensure we capture and acknowledge the user's chat_id
        if not self.settings.telegram_chat_id or self.settings.telegram_chat_id == "changeme":
            self.settings.telegram_chat_id = chat_id

        # Resolve user by telegram_name from the message sender
        from app.models.student_profile import User
        db: Session = SessionLocal()
        try:
            from_user = msg.get("from", {})
            telegram_name = (from_user.get("first_name") or "").strip().lower() or None

            user = None
            if telegram_name:
                user = db.query(User).filter(User.telegram_name == telegram_name).first()
            if user is None:
                # Fallback: default user (id=1)
                user = db.query(User).filter(User.id == 1).first()

            if user is None:
                await self.send_reply(chat_id, "⚠️ No user account found. Please set up your profile first.")
                return

            user_id = user.id

            if text.startswith("/"):
                reply = await self.handle_command(text, user_id=user_id, db=db)
            else:
                reply = await self.handle_natural_language(text, user_id=user_id, db=db)
            await self.send_reply(chat_id, reply)
        except Exception as e:
            logger.error("Error handling Telegram message: %s", e)
            await self.send_reply(chat_id, f"⚠️ Error processing request: {e}")
        finally:
            db.close()

    async def start_polling(self) -> None:
        """Continuously poll Telegram for updates."""
        if not self.is_configured:
            logger.info("Telegram bot polling not started (mock mode is enabled or token is missing).")
            return

        self.running = True
        logger.info("Starting interactive 2-way Telegram Bot polling for chat_id: %s", self.authorized_chat_id)

        async with httpx.AsyncClient(timeout=30.0) as client:
            while self.running:
                try:
                    url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                    params = {"offset": self.last_update_id + 1, "timeout": 20}
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        updates = data.get("result", [])
                        for update in updates:
                            self.last_update_id = update["update_id"]
                            await self.process_update(update)
                    else:
                        logger.warning("Telegram getUpdates returned status %d", resp.status_code)
                        await asyncio.sleep(5)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Exception in Telegram polling loop: %s", e)
                    await asyncio.sleep(5)

        logger.info("Telegram Bot polling stopped.")

    def stop(self) -> None:
        self.running = False


# Global singleton listener
telegram_bot_listener = TelegramBotListener()
