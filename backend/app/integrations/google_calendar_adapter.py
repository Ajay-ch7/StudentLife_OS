import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy.orm import Session

from app.integrations.google_auth import get_calendar_service, is_google_authenticated
from app.models.calendar_event import CalendarEvent

logger = logging.getLogger(__name__)


class GoogleCalendarAdapter:
    """Adapter for bi-directional synchronization with Google Calendar."""

    def __init__(self) -> None:
        self._service = None

    @property
    def service(self):
        if self._service is None:
            self._service = get_calendar_service()
        return self._service

    def is_connected(self) -> bool:
        """Return True if Google Calendar API service is authenticated and ready."""
        return self.service is not None

    def list_events(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        max_results: int = 50,
        calendar_id: str = "primary",
    ) -> list[dict[str, Any]]:
        """Fetch events within a time window from Google Calendar."""
        if not self.is_connected():
            logger.info("Google Calendar is not connected.")
            return []

        now = datetime.now(timezone.utc)
        t_min = (start_time or now).isoformat()
        t_max = (end_time or (now + timedelta(days=7))).isoformat()

        try:
            res = (
                self.service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=t_min,
                    timeMax=t_max,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            items = res.get("items", [])
            normalized = []
            for item in items:
                start_raw = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
                end_raw = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
                normalized.append({
                    "google_id": item.get("id"),
                    "title": item.get("summary", "Untitled"),
                    "description": item.get("description", ""),
                    "location": item.get("location", ""),
                    "starts_at": start_raw,
                    "ends_at": end_raw,
                    "status": item.get("status", "confirmed"),
                })
            return normalized
        except Exception as e:
            logger.error("Error fetching Google Calendar events: %s", e)
            return []

    def create_event(
        self,
        title: str,
        starts_at: datetime,
        ends_at: datetime,
        description: str = "",
        location: str = "",
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        """Create a new event on Google Calendar."""
        if not self.is_connected():
            return {"status": "failed", "error": "Google Calendar not connected"}

        body = {
            "summary": title,
            "description": description,
            "location": location,
            "start": {
                "dateTime": starts_at.isoformat(),
            },
            "end": {
                "dateTime": ends_at.isoformat(),
            },
        }

        try:
            created = self.service.events().insert(calendarId=calendar_id, body=body).execute()
            logger.info("Successfully created Google Calendar event: %s (%s)", title, created.get("id"))
            return {
                "status": "success",
                "google_id": created.get("id"),
                "html_link": created.get("htmlLink"),
                "title": title,
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
            }
        except Exception as e:
            logger.error("Failed to insert event into Google Calendar: %s", e)
            return {"status": "failed", "error": str(e)}

    def update_event(
        self,
        event_id: str,
        starts_at: datetime,
        ends_at: datetime,
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        """Move an existing Google Calendar event while preserving its details."""
        if not self.is_connected():
            return {"status": "failed", "error": "Google Calendar not connected"}

        try:
            event = self.service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            event["start"] = {"dateTime": starts_at.isoformat()}
            event["end"] = {"dateTime": ends_at.isoformat()}
            updated = self.service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event,
            ).execute()
            logger.info("Successfully rescheduled Google Calendar event: %s", event_id)
            return {
                "status": "success",
                "google_id": updated.get("id", event_id),
                "html_link": updated.get("htmlLink"),
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
            }
        except Exception as e:
            logger.error("Failed to reschedule Google Calendar event %s: %s", event_id, e)
            return {"status": "failed", "error": str(e)}

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        """Delete an event from Google Calendar by its Google event ID."""
        if not self.is_connected():
            return False
        try:
            self.service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            logger.info("Successfully deleted Google Calendar event: %s", event_id)
            return True
        except Exception as e:
            logger.error("Failed to delete event %s from Google Calendar: %s", event_id, e)
            return False

    def sync_to_local_db(
        self,
        db: Session,
        user_id: int,
        days_ahead: int = 14,
    ) -> dict[str, Any]:
        """
        Pull events from Google Calendar and merge them into the local SQLite database.
        Allows local scheduling and conflict checking to be fast and offline-capable.
        """
        if not self.is_connected():
            return {
                "synced_count": 0,
                "status": "not_connected",
                "message": "Google Calendar is not authenticated yet.",
            }

        now = datetime.now(timezone.utc)
        events = self.list_events(start_time=now - timedelta(days=1), end_time=now + timedelta(days=days_ahead))
        synced = 0
        newly_added: list[CalendarEvent] = []

        for item in events:
            try:
                starts_at = datetime.fromisoformat(item["starts_at"].replace("Z", "+00:00"))
                ends_at = datetime.fromisoformat(item["ends_at"].replace("Z", "+00:00"))
            except Exception:
                continue

            google_id = item.get("google_id")

            # Check if event already exists locally by google_event_id or title+time
            query = db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id)
            if google_id:
                existing = query.filter(
                    (CalendarEvent.google_event_id == google_id)
                    | ((CalendarEvent.title == item["title"]) & (CalendarEvent.starts_at == starts_at))
                ).first()
            else:
                existing = query.filter(
                    CalendarEvent.title == item["title"],
                    CalendarEvent.starts_at == starts_at,
                ).first()

            if not existing:
                new_event = CalendarEvent(
                    user_id=user_id,
                    google_event_id=google_id,
                    title=item["title"],
                    starts_at=starts_at,
                    ends_at=ends_at,
                    location=item["location"] or None,
                    event_type="commitment",
                    creation_notified=False,
                    reminded_day_before=False,
                )
                db.add(new_event)
                newly_added.append(new_event)
                synced += 1
            else:
                if google_id and not existing.google_event_id:
                    existing.google_event_id = google_id
                existing.ends_at = ends_at
                existing.location = item["location"] or None

        db.commit()

        return {
            "synced_count": synced,
            "total_google_events": len(events),
            "newly_created_events": [
                {
                    "id": e.id,
                    "title": e.title,
                    "starts_at": e.starts_at,
                    "ends_at": e.ends_at,
                    "location": e.location,
                    "google_event_id": e.google_event_id,
                }
                for e in newly_added
            ],
            "status": "success",
        }
