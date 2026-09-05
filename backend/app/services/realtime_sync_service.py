import asyncio
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import SessionLocal
from app.integrations.gmail_adapter import GmailAdapter
from app.integrations.google_calendar_adapter import GoogleCalendarAdapter
from app.models.calendar_event import CalendarEvent
from app.models.email_message import EmailMessage
from app.models.opportunity import Opportunity
from app.models.student_profile import User
from app.services.scheduling_service import conflict_reasons
from app.services.telegram_bot_listener import TelegramBotListener
from openclaw.workflows.email_to_action_workflow import EmailToActionWorkflow

logger = logging.getLogger(__name__)


class RealtimeSyncService:
    """
    Continuous autonomous background synchronization engine for Gmail and Google Calendar.
    Runs periodically to ensure newly received emails automatically trigger OpenClaw's
    Email-to-Action workflow with LLM reasoning, smart updates, proactive Telegram alerts,
    and automated calendar event tracking & day-before reminders.
    """

    def __init__(self, interval_seconds: int = 15) -> None:
        self.interval_seconds = interval_seconds
        self.gmail_adapter = GmailAdapter()
        self.calendar_adapter = GoogleCalendarAdapter()
        self.email_workflow = EmailToActionWorkflow()
        self.telegram = TelegramBotListener()
        self.settings = get_settings()
        self.is_running = False

    async def start_periodic_sync(self) -> None:
        """Start the continuous background polling loop."""
        self.is_running = True
        logger.info("RealtimeSyncService background worker started (interval: %ds).", self.interval_seconds)

        while self.is_running:
            try:
                db: Session = SessionLocal()
                try:
                    user = db.query(User).first()
                    if user:
                        await self.sync_gmail_inbox(db=db, user_id=user.id)
                        await self.sync_google_calendar(db=db, user_id=user.id)
                        await self.check_upcoming_reminders(db=db, user_id=user.id)
                finally:
                    db.close()
            except asyncio.CancelledError:
                logger.info("RealtimeSyncService task cancelled.")
                break
            except Exception as e:
                logger.error("Error in RealtimeSyncService iteration: %s", e)

            await asyncio.sleep(self.interval_seconds)

    def stop(self) -> None:
        """Stop the background worker."""
        self.is_running = False
        logger.info("RealtimeSyncService stopped.")

    async def sync_gmail_inbox(self, db: Session, user_id: int) -> dict[str, int]:
        """Fetch latest emails and autonomously run EmailToActionWorkflow on unprocessed ones."""
        new_messages = self.gmail_adapter.list_recent_messages(query="", max_results=10)
        if not new_messages:
            return {"new_emails": 0, "tasks_created": 0}

        new_count = 0
        tasks_count = 0

        for msg in new_messages:
            gmail_id = str(msg.get("id"))
            existing = db.query(EmailMessage).filter(
                EmailMessage.user_id == user_id,
                EmailMessage.gmail_id == gmail_id,
            ).first()

            # Autonomously trigger only if email is new or unprocessed
            if not existing or existing.processing_status not in ("processed", "processing", "pending_approval", "failed"):
                new_count += 1
                logger.info(
                    "Autonomous Trigger: New email detected '%s' (ID: %s). Initiating OpenClaw workflow.",
                    msg.get("subject"),
                    gmail_id,
                )

                workflow_result = await self.email_workflow.run(
                    user_id=user_id,
                    db=db,
                    payload=msg,
                )

                if workflow_result.get("status") == "completed":
                    created = len(workflow_result.get("created_tasks", []))
                    updated = len(workflow_result.get("updated_tasks", []))
                    tasks_count += (created + updated)

        return {"new_emails": new_count, "tasks_created": tasks_count}

    async def sync_google_calendar(self, db: Session, user_id: int) -> int:
        """Sync upcoming calendar events into SQLite and alert on newly created events."""
        if not self.calendar_adapter.is_connected():
            return 0

        res = self.calendar_adapter.sync_to_local_db(db, user_id=user_id, days_ahead=14)
        synced = res.get("synced_count", 0)
        target_chat_id = self.settings.telegram_chat_id

        # Query any upcoming event whose creation has not been alerted yet
        now_utc = datetime.now(timezone.utc)
        unnotified_events = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.user_id == user_id,
                CalendarEvent.creation_notified == False,
                CalendarEvent.ends_at >= now_utc - timedelta(hours=2),
            )
            .order_by(CalendarEvent.starts_at.asc())
            .all()
        )

        if unnotified_events:
            logger.info("Real-time Sync: Found %d unnotified calendar event(s).", len(unnotified_events))

            for event in unnotified_events:

                # Format time and details
                start_dt = event.starts_at
                end_dt = event.ends_at
                time_str = f"{start_dt.strftime('%a, %b %d • %I:%M %p')} - {end_dt.strftime('%I:%M %p')}"
                loc_str = f"\n📍 Location: {event.location}" if event.location else ""

                # Run conflict check
                conflicts = conflict_reasons(
                    db=db,
                    user_id=user_id,
                    starts_at=start_dt,
                    ends_at=end_dt,
                    exclude_event_id=event.id,
                )
                if conflicts:
                    conflict_str = "⚠️ Schedule Overlap Detected:\n" + "\n".join(f"• {c}" for c in conflicts)
                else:
                    conflict_str = "✅ No schedule conflicts detected."

                alert_text = (
                    "📅 New Calendar Event Created\n\n"
                    f"📌 Title: {event.title}\n"
                    f"🕒 Time: {time_str}"
                    f"{loc_str}\n\n"
                    f"Status: {conflict_str}"
                )

                if target_chat_id:
                    try:
                        delivered = await self.telegram.send_alert(
                            db=db,
                            chat_id=target_chat_id,
                            text=alert_text,
                            alert_key=f"calendar_event_created:{event.id}",
                        )
                        if delivered:
                            logger.info("Delivered Telegram alert for new calendar event '%s'", event.title)
                    except Exception as err:
                        logger.warning("Could not dispatch calendar event alert to Telegram: %s", err)

                event.creation_notified = True
                db.commit()

        return synced

    async def check_upcoming_reminders(self, db: Session, user_id: int) -> int:
        """
        Check for upcoming events occurring tomorrow (the day before the event date)
        and proactively dispatch a Telegram reminder.
        """
        target_chat_id = self.settings.telegram_chat_id
        if not target_chat_id:
            return 0

        now_utc = datetime.now(timezone.utc)
        user = db.query(User).filter(User.id == user_id).first()
        tz = timezone.utc
        if user and user.profile and getattr(user.profile, "timezone", None):
            try:
                import zoneinfo
                tz = zoneinfo.ZoneInfo(user.profile.timezone)
            except Exception:
                tz = timezone.utc

        now_local = datetime.now(tz)
        today_date = now_local.date()
        tomorrow_date = today_date + timedelta(days=1)

        unreminded = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.user_id == user_id,
                CalendarEvent.reminded_day_before == False,
            )
            .all()
        )

        reminders_sent = 0

        for event in unreminded:
            ev_start = event.starts_at
            if ev_start.tzinfo is None:
                ev_start = ev_start.replace(tzinfo=timezone.utc)
            ev_start_local = ev_start.astimezone(tz)
            ev_date = ev_start_local.date()

            # If the event date is tomorrow, dispatch the "day before" reminder
            if ev_date == tomorrow_date:
                ev_end = event.ends_at
                if ev_end.tzinfo is None:
                    ev_end = ev_end.replace(tzinfo=timezone.utc)
                ev_end_local = ev_end.astimezone(tz)

                time_str = f"{ev_start_local.strftime('%I:%M %p')} - {ev_end_local.strftime('%I:%M %p')}"
                date_str = ev_start_local.strftime('%A, %b %d')
                loc_str = f"\n📍 Location: {event.location}" if event.location else ""

                reminder_text = (
                    "⏰ Upcoming Event Reminder (Tomorrow)\n\n"
                    f"📌 Event: {event.title}\n"
                    f"📅 Date: Tomorrow ({date_str})\n"
                    f"🕒 Time: {time_str}"
                    f"{loc_str}\n\n"
                    "💡 Make sure to prepare any required materials in advance!"
                )

                try:
                    delivered = await self.telegram.send_alert(
                        db=db,
                        chat_id=target_chat_id,
                        text=reminder_text,
                        alert_key=f"calendar_event_reminder:{event.id}",
                    )
                    if delivered:
                        logger.info("Sent day-before reminder for event '%s' to %s", event.title, target_chat_id)
                        reminders_sent += 1
                except Exception as err:
                    logger.warning("Could not dispatch event reminder to Telegram: %s", err)

                event.reminded_day_before = True
                db.commit()

            elif ev_date <= today_date:
                # Event is today or in the past; mark reminded to avoid stale reminders
                event.reminded_day_before = True
                db.commit()

        return reminders_sent


realtime_sync_service = RealtimeSyncService(interval_seconds=15)
