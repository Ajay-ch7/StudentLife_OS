"""
Script to reset mock data and synchronize REAL data from Google Calendar & Gmail
for Kriti Karunam (kritikarunam3@gmail.com).
"""
import sys
import os
import asyncio
from pathlib import Path
from datetime import datetime, timezone

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.database import SessionLocal, init_db, engine
from app.models.activity_log import ActivityLog
from app.models.agent_action import AgentAction
from app.models.approval_request import ApprovalRequest
from app.models.application import Application
from app.models.assignment import Assignment
from app.models.calendar_event import CalendarEvent
from app.models.course import Course
from app.models.deadline import Deadline
from app.models.dsa_problem import DSAProblem
from app.models.dsa_progress import DSAProgress
from app.models.exam import Exam
from app.models.opportunity import Opportunity
from app.models.note import Note
from app.models.project import Project
from app.models.student_profile import StudentProfile, User
from app.models.study_material import StudyMaterial
from app.models.study_plan import StudyPlan
from app.models.study_session import StudySession
from app.models.task import Task
from app.integrations.google_auth import is_google_authenticated
from app.integrations.google_calendar_adapter import GoogleCalendarAdapter
from app.integrations.gmail_adapter import GmailAdapter
from app.services.inbox_service import InboxService
from app.services.gemini_service import GeminiService


async def main():
    print("==================================================")
    print(" StudentLife OS - Real Google Data Synchronization")
    print("==================================================")

    if not is_google_authenticated():
        print("[ERROR] Google account is not authenticated yet. Please run connect_google.py first.")
        sys.exit(1)

    init_db()
    db = SessionLocal()

    try:
        # 1. Clean out mock / dummy data
        print("\n[1/4] Cleaning mock/dummy records...")
        db.query(ActivityLog).delete()
        db.query(AgentAction).delete()
        db.query(ApprovalRequest).delete()
        db.query(CalendarEvent).delete()
        db.query(Deadline).delete()
        db.query(Assignment).delete()
        db.query(Exam).delete()
        db.query(Course).delete()
        db.query(Task).delete()
        db.query(StudyPlan).delete()
        db.query(StudySession).delete()
        db.query(Note).delete()
        db.query(StudyMaterial).delete()
        db.query(Project).delete()
        db.query(Application).delete()
        db.query(Opportunity).delete()
        db.commit()
        print("  -> Cleaned all dummy tasks, events, approvals, assignments, and logs.")

        # 2. Setup Real User Profile
        print("\n[2/4] Setting up real user profile...")
        user = db.query(User).filter(User.email == "kritikarunam3@gmail.com").first()
        if not user:
            # Check if there is an existing user to update
            user = db.query(User).first()
            if user:
                user.email = "kritikarunam3@gmail.com"
                user.full_name = "Kriti Karunam"
                user.telegram_name = "kriti"
            else:
                user = User(
                    email="kritikarunam3@gmail.com",
                    full_name="Kriti Karunam",
                    telegram_name="kriti",
                )
                db.add(user)
            db.commit()
            db.refresh(user)
        else:
            user.full_name = "Kriti Karunam"
            user.telegram_name = "kriti"
            db.commit()
            db.refresh(user)

        # Profile
        profile = user.profile
        if not profile:
            profile = StudentProfile(
                user_id=user.id,
                college="University Engineering",
                degree="Computer Science & Engineering",
                year=3,
                cgpa=8.8,
                target_roles="Software Engineer, AI/ML Intern",
                target_companies="Google, Microsoft, Adobe",
                skills="Python, Data Structures, Algorithms, React, FastAPI, System Design",
                preferred_locations="Hyderabad, Bangalore, Remote",
                available_study_hours=4.0,
                preferred_study_times="Morning (8 AM - 11 AM), Evening (6 PM - 9 PM)",
                timezone="Asia/Kolkata",
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)

        print(f"  -> User verified: {user.full_name} ({user.email}) [telegram: @{user.telegram_name}]")

        # 3. Synchronize Google Calendar
        print("\n[3/4] Synchronizing Google Calendar...")
        cal_adapter = GoogleCalendarAdapter()
        sync_res = cal_adapter.sync_to_local_db(db, user_id=user.id, days_ahead=30)
        print(f"  -> Google Calendar Sync Status: {sync_res.get('status')}")
        print(f"  -> Google Events Found: {sync_res.get('total_google_events', 0)}")
        print(f"  -> Synced into Local DB: {sync_res.get('synced_count', 0)}")

        # 4. Scan Gmail for actual assignments, deadlines & opportunities
        print("\n[4/4] Scanning connected Gmail for emails, assignments & opportunities...")
        gmail_adapter = GmailAdapter()
        gemini_service = GeminiService()
        inbox_service = InboxService(gemini_service)

        recent_msgs = gmail_adapter.list_recent_messages(query="", max_results=15)
        print(f"  -> Retrieved {len(recent_msgs)} recent emails from Gmail.")

        tasks_created = 0
        opportunities_created = 0

        for msg in recent_msgs:
            sender = msg.get("from", "")
            subject = msg.get("subject", "")
            body = msg.get("body") or msg.get("snippet", "")
            date_str = msg.get("date", "")

            # Check if this is an opportunity email (e.g. Microsoft, Adobe, Unstop)
            is_opportunity = any(k in (sender + subject).lower() for k in ["career", "intern", "job", "opportunity", "unstop", "hiring"])
            if is_opportunity:
                opp = Opportunity(
                    user_id=user.id,
                    title=subject[:250],
                    company=sender.split("<")[0].strip()[:250] or "Tech Company",
                    source="gmail",
                    url="https://mail.google.com",
                    description=body[:1000],
                    required_skills="Software Engineering, Computer Science",
                    match_score=0.92,
                )
                db.add(opp)
                opportunities_created += 1

            # Process with Gemini Inbox extraction
            content = f"From: {sender}\nSubject: {subject}\nDate: {date_str}\n\n{body}"
            extraction = await inbox_service.process_content(
                db=db,
                user_id=user.id,
                content=content,
                source_type="email",
                source_metadata={"email_id": msg.get("id"), "from": sender, "subject": subject},
                dry_run=False,
            )
            tasks_created += len(extraction.get("tasks_created", []))

        db.commit()
        print(f"  -> Extracted & Created Tasks from Gmail: {tasks_created}")
        print(f"  -> Extracted & Saved Opportunities from Gmail: {opportunities_created}")

        # Summary
        print("\n==================================================")
        print(" [SUCCESS] System Updated with Real Data!")
        print("==================================================")
        print(f" User: {user.full_name} ({user.email})")
        print(f" Local Calendar Events: {db.query(CalendarEvent).filter(CalendarEvent.user_id == user.id).count()}")
        print(f" Active Tasks: {db.query(Task).filter(Task.user_id == user.id).count()}")
        print(f" Opportunities: {db.query(Opportunity).filter(Opportunity.user_id == user.id).count()}")
        print("==================================================")

    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
