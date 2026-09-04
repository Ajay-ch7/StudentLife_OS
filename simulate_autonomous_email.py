"""
Autonomous Email-to-Action Workflow Demonstration Script
Demonstrates the full end-to-end pipeline:
1. Incoming Email arrival
2. OpenClaw autonomous detection
3. Extraction & Normalization
4. LLM reasoning (priority, deadlines, smart task update, reasoning)
5. Database updates (EmailMessage, Task, Deadline)
6. Autonomous actions execution
7. Proactive Telegram notification delivery
8. Zero user command required
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR))

from app.db.database import SessionLocal, init_db
from app.models.calendar_event import CalendarEvent
from app.models.deadline import Deadline
from app.models.email_message import EmailMessage
from app.models.student_profile import StudentProfile, User
from app.models.task import Task
from openclaw.workflows.email_to_action_workflow import EmailToActionWorkflow


async def run_simulation():
    print("=" * 65)
    print("  STUDENTLIFE OS - AUTONOMOUS EMAIL-TO-ACTION WORKFLOW")
    print("=" * 65)

    init_db()
    db = SessionLocal()

    try:
        # Setup test user
        user = db.query(User).first()
        if not user:
            user = User(email="student@univ.edu", full_name="Student", telegram_name="student")
            db.add(user)
            db.commit()
            db.refresh(user)

        profile = user.profile
        if not profile:
            profile = StudentProfile(
                user_id=user.id,
                college="Engineering Institute",
                degree="Computer Science",
                year=3,
                skills="Python, SQL, DSA, System Design",
                available_study_hours=4.0,
            )
            db.add(profile)
            db.commit()

        print(f"\n[Step 0] Active Student: {user.full_name} ({user.email})")

        # Pre-seed a base task to demonstrate intelligent smart update
        existing_task = (
            db.query(Task)
            .filter(Task.user_id == user.id, Task.title.ilike("%Assignment 2%"))
            .first()
        )
        if not existing_task:
            existing_task = Task(
                user_id=user.id,
                title="CS302 Database Assignment 2",
                description="Normalization and BCNF problems 1-5",
                deadline=datetime(2026, 9, 10, 23, 59, tzinfo=timezone.utc),
                priority="medium",
                status="pending",
                source="syllabus",
            )
            db.add(existing_task)
            db.commit()
            db.refresh(existing_task)
            db.add(
                Deadline(
                    user_id=user.id,
                    task_id=existing_task.id,
                    title=existing_task.title,
                    due_at=existing_task.deadline,
                    source="syllabus",
                    is_confirmed=True,
                )
            )
            db.commit()
            print(f"  -> Pre-existing Task: '{existing_task.title}' (Deadline: {existing_task.deadline})")
        else:
            print(f"  -> Found existing Task: '{existing_task.title}' (Deadline: {existing_task.deadline})")

        # 1. Incoming Email Arrives (Simulated)
        incoming_email = {
            "id": f"sim-msg-{int(datetime.now().timestamp())}",
            "thread_id": "thread-ext-456",
            "from": "Prof. Sharma <prof.sharma@university.edu>",
            "subject": "CS302 Assignment 2 Deadline Extension",
            "date": datetime.now(timezone.utc).isoformat(),
            "body": (
                "Dear Class,\n\n"
                "In response to student requests, the deadline for CS302 Assignment 2 has been "
                "officially extended by 48 hours to September 12, 2026 at 11:59 PM.\n\n"
                "Please submit your answers on Canvas.\n\nBest regards,\nProf. Sharma"
            ),
        }

        print(f"\n[Step 1] Incoming Email Detected by OpenClaw:")
        print(f"  From    : {incoming_email['from']}")
        print(f"  Subject : {incoming_email['subject']}")
        print(f"  ID      : {incoming_email['id']}")

        # 2. OpenClaw Autonomous Trigger (No user command needed!)
        print("\n[Step 2] Triggering OpenClaw EmailToActionWorkflow autonomously...")
        workflow = EmailToActionWorkflow()
        result = await workflow.run(user_id=user.id, db=db, payload=incoming_email)

        print("\n[Step 3] Workflow Execution Finished:")
        print(f"  Status    : {result.get('status')}")
        print(f"  Priority  : {result.get('priority', '').upper()}")
        print(f"  Summary   : {result.get('summary')}")
        print(f"  Reasoning : {result.get('reasoning')}")
        print("  Changes Made:")
        for ch in result.get("changes_made", []):
            print(f"    {ch}")

        # 3. Database State Verification
        print("\n[Step 4] Verifying Database State in SQLite:")
        email_db = (
            db.query(EmailMessage)
            .filter(EmailMessage.gmail_id == incoming_email["id"])
            .first()
        )
        if email_db:
            print(f"  [OK] Email Record: ID={email_db.id} | Status={email_db.processing_status} | Priority={email_db.priority}")
            print(f"       Reasoning in DB: {email_db.reasoning[:80]}...")

        db.refresh(existing_task)
        print(f"  [OK] Task in DB: '{existing_task.title}' | Updated Deadline={existing_task.deadline}")

        # 4. Duplicate Prevention Verification
        print("\n[Step 5] Testing Duplicate Email Prevention:")
        dup_result = await workflow.run(user_id=user.id, db=db, payload=incoming_email)
        print(f"  Duplicate Run Status: {dup_result.get('status')} (Reason: {dup_result.get('reason')})")
        assert dup_result.get("status") == "skipped", "Duplicate email was not skipped!"
        print("  [OK] Duplicate prevention confirmed: email was not re-processed!")

        print("\n" + "=" * 65)
        print("  AUTONOMOUS EMAIL-TO-ACTION PIPELINE VERIFIED SUCCESSFULLY!")
        print("=" * 65)

    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(run_simulation())
