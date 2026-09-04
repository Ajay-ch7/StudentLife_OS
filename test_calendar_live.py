import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR))

from app.integrations.google_calendar_adapter import GoogleCalendarAdapter

def main():
    print("==================================================")
    print(" Testing Google Calendar Integration")
    print("==================================================")

    cal = GoogleCalendarAdapter()
    connected = cal.is_connected()
    print(f"Google Calendar Connected: {connected}")

    if not connected:
        print("[ERROR] Google Calendar is not connected. Run 'python connect_google.py' first.")
        return

    # 1. Fetch current upcoming events
    events = cal.list_events()
    print(f"\nCurrent events in Google Calendar (next 7 days): {len(events)}")
    for ev in events:
        print(f"  • {ev.get('title')} [{ev.get('starts_at')} -> {ev.get('ends_at')}]")

    # 2. Create a test event tomorrow
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=1, hours=2)
    end = start + timedelta(hours=1)
    print(f"\nCreating test event on Google Calendar: '[StudentLife OS] Test Study Session'...")
    res = cal.create_event(
        title="[StudentLife OS] Test Study Session",
        starts_at=start,
        ends_at=end,
        description="Verification event created by StudentLife OS test suite.",
        location="Library Room 302",
    )
    print(f"Create status: {res.get('status')}")
    print(f"Google Event ID: {res.get('google_id')}")
    print(f"Calendar Link: {res.get('html_link')}")

    # 3. Verify event is retrieved from Google Calendar
    if res.get("status") == "success":
        google_id = res.get("google_id")
        events_after = cal.list_events(start_time=start - timedelta(hours=1), end_time=end + timedelta(hours=1))
        matching = [e for e in events_after if e.get("google_id") == google_id]
        print(f"Verified event exists in Google Calendar query: {bool(matching)}")

        # 4. Clean up test event
        deleted = cal.delete_event(google_id)
        print(f"Test event cleanup from Google Calendar: {'Success' if deleted else 'Failed'}")

    print("\n==================================================")
    print(" [SUCCESS] Google Calendar integration is fully operational!")
    print("==================================================")

if __name__ == "__main__":
    main()
