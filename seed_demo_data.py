import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR))

from app.db.database import SessionLocal, init_db
from app.models.student_profile import User, StudentProfile
from app.models.calendar_event import CalendarEvent
from app.models.task import Task
from app.models.deadline import Deadline
from app.models.approval_request import ApprovalRequest
from app.models.assignment import Assignment
from app.models.exam import Exam
from app.models.study_session import StudySession
from app.models.course import Course
from app.models.dsa_problem import DSAProblem
from app.models.dsa_progress import DSAProgress
from app.models.opportunity import Opportunity
from app.models.study_plan import StudyPlan
from app.models.note import Note
from app.models.project import Project
from app.models.study_material import StudyMaterial


def seed() -> None:
    # Ensure tables exist (handles migrations too)
    init_db()

    db = SessionLocal()
    try:
        # ───────────────────────────────────────────────────
        # 1. User & Profile  (matches the default user seed)
        # ───────────────────────────────────────────────────
        user = db.query(User).filter(User.email == "kriti@university.edu").first()
        if not user:
            user = User(
                email="kriti@university.edu",
                full_name="Kriti",
                telegram_name="kriti",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            user.full_name = "Kriti"
            user.telegram_name = "kriti"
            db.commit()
            db.refresh(user)

        profile = (
            db.query(StudentProfile)
            .filter(StudentProfile.user_id == user.id)
            .first()
        )
        profile_data = dict(
            college="National Institute of Technology, Warangal",
            degree="B.Tech Computer Science & Engineering",
            year=3,
            cgpa=8.85,
            skills="Python, FastAPI, React, TypeScript, SQL, DSA, System Design, Docker",
            target_roles="Software Engineer Intern, Backend Developer, Full-Stack Developer",
            target_companies="Google, Microsoft, Amazon, Flipkart, Razorpay",
            available_study_hours=5.0,
            preferred_study_times="Evenings (6 PM – 10 PM), Early mornings (6 AM – 8 AM)",
            preferred_locations="Hyderabad, Bangalore, Remote",
            timezone="Asia/Kolkata",
        )
        if not profile:
            profile = StudentProfile(user_id=user.id, **profile_data)
            db.add(profile)
        else:
            for key, value in profile_data.items():
                setattr(profile, key, value)
        db.commit()

        # ───────────────────────────────────────────────
        # 2. Clean old demo data for a fresh state
        # ───────────────────────────────────────────────
        for model in (
            CalendarEvent, Task, Deadline, ApprovalRequest,
            Assignment, Exam, StudySession, Course,
            DSAProblem, DSAProgress, Opportunity,
            StudyPlan, Note, Project, StudyMaterial,
        ):
            db.query(model).filter(model.user_id == user.id).delete()
        db.commit()

        now = datetime.now(timezone.utc)
        today = now.replace(minute=0, second=0, microsecond=0)

        # ───────────────────────────────────────────────
        # 3. Courses
        # ───────────────────────────────────────────────
        courses = [
            Course(user_id=user.id, code="CS301", name="Database Management Systems", semester="Fall 2026"),
            Course(user_id=user.id, code="CS302", name="Operating Systems", semester="Fall 2026"),
            Course(user_id=user.id, code="CS303", name="Computer Networks", semester="Fall 2026"),
            Course(user_id=user.id, code="CS304", name="Design & Analysis of Algorithms", semester="Fall 2026"),
            Course(user_id=user.id, code="CS399", name="Capstone Project", semester="Fall 2026"),
        ]
        db.add_all(courses)
        db.flush()

        # ───────────────────────────────────────────────
        # 4. Calendar Events (5 today, with a conflict)
        # ───────────────────────────────────────────────
        events = [
            CalendarEvent(
                user_id=user.id,
                title="Database Systems Lecture",
                starts_at=today.replace(hour=10, minute=0),
                ends_at=today.replace(hour=11, minute=30),
                location="Auditorium Hall B",
                event_type="class",
            ),
            CalendarEvent(
                user_id=user.id,
                title="Operating Systems Lab",
                starts_at=today.replace(hour=14, minute=0),
                ends_at=today.replace(hour=15, minute=30),
                location="CS Lab 2",
                event_type="lab",
            ),
            CalendarEvent(
                user_id=user.id,
                title="Capstone Project Team Sync",
                starts_at=today.replace(hour=16, minute=0),
                ends_at=today.replace(hour=17, minute=0),
                location="Google Meet",
                event_type="meeting",
            ),
            CalendarEvent(
                user_id=user.id,
                title="DSA Problem Solving (Graphs & Trees)",
                starts_at=today.replace(hour=16, minute=30),  # Overlaps with Team Sync!
                ends_at=today.replace(hour=17, minute=30),
                location="Study Room 3",
                event_type="study",
            ),
            CalendarEvent(
                user_id=user.id,
                title="Deep Work: Distributed Systems Revision",
                starts_at=today.replace(hour=19, minute=0),
                ends_at=today.replace(hour=20, minute=30),
                location="Home Desk",
                event_type="study",
            ),
            # Tomorrow
            CalendarEvent(
                user_id=user.id,
                title="Computer Networks Tutorial",
                starts_at=(today + timedelta(days=1)).replace(hour=9, minute=0),
                ends_at=(today + timedelta(days=1)).replace(hour=10, minute=0),
                location="Room 204",
                event_type="class",
            ),
            CalendarEvent(
                user_id=user.id,
                title="Mock Interview Practice",
                starts_at=(today + timedelta(days=1)).replace(hour=15, minute=0),
                ends_at=(today + timedelta(days=1)).replace(hour=16, minute=0),
                location="Career Center",
                event_type="meeting",
            ),
        ]
        db.add_all(events)

        # ───────────────────────────────────────────────
        # 5. Tasks & Deadlines (urgent + normal mix)
        # ───────────────────────────────────────────────
        d1 = now + timedelta(hours=18)
        d2 = now + timedelta(days=2)
        d3 = now + timedelta(days=4)
        d4 = now + timedelta(days=7)

        tasks = [
            Task(
                user_id=user.id,
                title="Submit Database Normalization Assignment",
                description="Complete BCNF and 3NF functional dependency proofs. Include examples from Auditorium database schema.",
                priority="urgent",
                status="pending",
                deadline=d1,
                category="academic",
                estimated_effort_hours=3,
            ),
            Task(
                user_id=user.id,
                title="Implement LRU Cache & Min-Heap for Interview Prep",
                description="Solve top 5 Amazon tagged questions on LeetCode. Focus on time/space complexity analysis.",
                priority="high",
                status="pending",
                deadline=d2,
                category="career",
                estimated_effort_hours=4,
            ),
            Task(
                user_id=user.id,
                title="Review Operating Systems Virtual Memory Slides",
                description="Page tables, TLB hits, and page replacement algorithms (LRU, FIFO, Optimal).",
                priority="medium",
                status="pending",
                deadline=d3,
                category="academic",
                estimated_effort_hours=2,
            ),
            Task(
                user_id=user.id,
                title="Update Resume with StudentLife OS Project",
                description="Add FastAPI, OpenClaw, Gemini integration, and Telegram bot bullet points.",
                priority="high",
                status="pending",
                deadline=d4,
                category="career",
                estimated_effort_hours=1,
            ),
            Task(
                user_id=user.id,
                title="Write Capstone Project Mid-Semester Report",
                description="System architecture diagrams, tech stack justification, and progress milestones.",
                priority="high",
                status="in_progress",
                deadline=d3,
                category="academic",
                estimated_effort_hours=5,
            ),
            Task(
                user_id=user.id,
                title="Practice System Design: URL Shortener",
                description="Cover high-level design, database schema, caching strategy, and load balancing.",
                priority="medium",
                status="pending",
                deadline=d4,
                category="career",
                estimated_effort_hours=3,
            ),
        ]
        db.add_all(tasks)

        deadlines = [
            Deadline(
                user_id=user.id,
                title="Database Normalization Assignment Due",
                due_at=d1,
                is_confirmed=True,
                source="canvas",
            ),
            Deadline(
                user_id=user.id,
                title="Google Summer Internship Applications Close",
                due_at=d2,
                is_confirmed=True,
                source="careers",
            ),
            Deadline(
                user_id=user.id,
                title="OS Lab Report Submission",
                due_at=d3,
                is_confirmed=True,
                source="canvas",
            ),
            Deadline(
                user_id=user.id,
                title="Capstone Mid-Semester Report",
                due_at=d3,
                is_confirmed=True,
                source="department",
            ),
        ]
        db.add_all(deadlines)

        # ───────────────────────────────────────────────
        # 6. Assignments
        # ───────────────────────────────────────────────
        assignments = [
            Assignment(
                user_id=user.id,
                course_name="Database Management Systems",
                title="Normalization to BCNF – Functional Dependencies",
                description="Given a set of FDs, decompose relations to BCNF. Show lossless-join and dependency preservation.",
                due_at=d1,
                status="pending",
            ),
            Assignment(
                user_id=user.id,
                course_name="Operating Systems",
                title="Virtual Memory Simulation Lab",
                description="Implement FIFO, LRU, and Optimal page replacement algorithms in Python. Compare hit ratios.",
                due_at=d3,
                status="pending",
            ),
            Assignment(
                user_id=user.id,
                course_name="Computer Networks",
                title="TCP Congestion Control Analysis",
                description="Trace TCP Reno and CUBIC behavior through packet captures. Analyze slow-start and congestion avoidance.",
                due_at=d4,
                status="pending",
            ),
            Assignment(
                user_id=user.id,
                course_name="Design & Analysis of Algorithms",
                title="Dynamic Programming Problem Set",
                description="Solve: Longest Common Subsequence, Matrix Chain Multiplication, and Knapsack (0/1 and Unbounded).",
                due_at=d2,
                status="submitted",
            ),
        ]
        db.add_all(assignments)

        # ───────────────────────────────────────────────
        # 7. Exams
        # ───────────────────────────────────────────────
        exams = [
            Exam(
                user_id=user.id,
                course_name="Database Management Systems",
                title="DBMS Mid-Semester Exam",
                starts_at=now + timedelta(days=12),
                notes="Covers: ER diagrams, Relational Algebra, SQL, Normalization up to BCNF.",
            ),
            Exam(
                user_id=user.id,
                course_name="Operating Systems",
                title="OS Mid-Semester Exam",
                starts_at=now + timedelta(days=14),
                notes="Covers: Process scheduling, Synchronization, Deadlocks, Memory management.",
            ),
            Exam(
                user_id=user.id,
                course_name="Design & Analysis of Algorithms",
                title="DAA Mid-Semester Exam",
                starts_at=now + timedelta(days=16),
                notes="Covers: Divide & Conquer, Greedy, DP, Graph algorithms (BFS, DFS, Dijkstra).",
            ),
        ]
        db.add_all(exams)

        # ───────────────────────────────────────────────
        # 8. Study Sessions
        # ───────────────────────────────────────────────
        sessions = [
            StudySession(
                user_id=user.id,
                topic="DBMS: Normalization Deep Dive",
                planned_start=today.replace(hour=19, minute=0),
                planned_end=today.replace(hour=20, minute=30),
                status="planned",
                notes="Focus on BCNF decomposition algorithm and examples.",
            ),
            StudySession(
                user_id=user.id,
                topic="DSA: Graph Traversals (BFS, DFS, Topological Sort)",
                planned_start=(today + timedelta(days=1)).replace(hour=18, minute=0),
                planned_end=(today + timedelta(days=1)).replace(hour=19, minute=30),
                status="planned",
                notes="Solve at least 3 LeetCode medium problems.",
            ),
            StudySession(
                user_id=user.id,
                topic="OS: Virtual Memory & Page Replacement",
                planned_start=(today + timedelta(days=2)).replace(hour=18, minute=0),
                planned_end=(today + timedelta(days=2)).replace(hour=20, minute=0),
                status="planned",
                notes="Implement FIFO and LRU simulators. Compare page fault rates.",
            ),
            StudySession(
                user_id=user.id,
                topic="Computer Networks: TCP/IP Stack Revision",
                planned_start=(today - timedelta(days=1)).replace(hour=19, minute=0),
                planned_end=(today - timedelta(days=1)).replace(hour=20, minute=0),
                actual_start=(today - timedelta(days=1)).replace(hour=19, minute=10),
                actual_end=(today - timedelta(days=1)).replace(hour=20, minute=5),
                status="completed",
                notes="Covered application, transport, and network layers. Need to revisit sliding window.",
            ),
        ]
        db.add_all(sessions)

        # ───────────────────────────────────────────────
        # 9. DSA Problems (solved history)
        # ───────────────────────────────────────────────
        today_date = date.today()
        dsa_problems = [
            DSAProblem(user_id=user.id, title="Two Sum", topic="Arrays", difficulty="easy", attempts=1, solved_on=today_date - timedelta(days=6)),
            DSAProblem(user_id=user.id, title="Valid Parentheses", topic="Stacks", difficulty="easy", attempts=1, solved_on=today_date - timedelta(days=5)),
            DSAProblem(user_id=user.id, title="Merge Two Sorted Lists", topic="Linked Lists", difficulty="easy", attempts=1, solved_on=today_date - timedelta(days=5)),
            DSAProblem(user_id=user.id, title="Binary Tree Level Order Traversal", topic="Trees", difficulty="medium", attempts=2, solved_on=today_date - timedelta(days=4)),
            DSAProblem(user_id=user.id, title="Course Schedule (Topological Sort)", topic="Graphs", difficulty="medium", attempts=2, solved_on=today_date - timedelta(days=3), needs_revision=True),
            DSAProblem(user_id=user.id, title="LRU Cache", topic="Design", difficulty="medium", attempts=3, solved_on=today_date - timedelta(days=2), needs_revision=True),
            DSAProblem(user_id=user.id, title="Word Ladder", topic="Graphs", difficulty="hard", attempts=4, solved_on=today_date - timedelta(days=1), needs_revision=True),
            DSAProblem(user_id=user.id, title="Longest Increasing Subsequence", topic="Dynamic Programming", difficulty="medium", attempts=2, solved_on=today_date),
            DSAProblem(user_id=user.id, title="Number of Islands", topic="Graphs", difficulty="medium", attempts=1, solved_on=today_date),
            DSAProblem(user_id=user.id, title="Kth Largest Element", topic="Heaps", difficulty="medium", attempts=1, solved_on=today_date),
        ]
        db.add_all(dsa_problems)

        dsa_progress = [
            DSAProgress(user_id=user.id, topic="Arrays", solved_count=12, revision_count=2),
            DSAProgress(user_id=user.id, topic="Stacks", solved_count=8, revision_count=1),
            DSAProgress(user_id=user.id, topic="Linked Lists", solved_count=7, revision_count=1),
            DSAProgress(user_id=user.id, topic="Trees", solved_count=10, revision_count=3),
            DSAProgress(user_id=user.id, topic="Graphs", solved_count=6, revision_count=2),
            DSAProgress(user_id=user.id, topic="Dynamic Programming", solved_count=9, revision_count=4),
            DSAProgress(user_id=user.id, topic="Design", solved_count=3, revision_count=1),
            DSAProgress(user_id=user.id, topic="Heaps", solved_count=4, revision_count=0),
        ]
        db.add_all(dsa_progress)

        # ───────────────────────────────────────────────
        # 10. Opportunities (internships/jobs)
        # ───────────────────────────────────────────────
        opportunities = [
            Opportunity(
                user_id=user.id,
                title="Software Engineer Intern – Summer 2027",
                company="Google",
                description="Work on Google Cloud infrastructure. Focus on distributed systems and API design. Python/Go preferred.",
                source="careers",
                url="https://careers.google.com/jobs/internships",
                required_skills="Python, Distributed Systems, Data Structures, Algorithms",
                match_score=0.92,
            ),
            Opportunity(
                user_id=user.id,
                title="Backend Developer Intern",
                company="Razorpay",
                description="Build high-throughput payment processing APIs. FastAPI/Django experience preferred. Work on real-time webhooks.",
                source="linkedin",
                url="https://razorpay.com/careers",
                required_skills="Python, FastAPI, PostgreSQL, Redis, Docker",
                match_score=0.88,
            ),
            Opportunity(
                user_id=user.id,
                title="SDE Intern – Platform Team",
                company="Microsoft",
                description="Contribute to Azure platform services. Strong CS fundamentals required. C++/Python.",
                source="careers",
                url="https://careers.microsoft.com/students",
                required_skills="C++, Python, System Design, OS concepts",
                match_score=0.85,
            ),
            Opportunity(
                user_id=user.id,
                title="Full-Stack Developer Intern",
                company="Flipkart",
                description="Build customer-facing features on Flipkart's e-commerce platform. React + Java/Python backend.",
                source="campus",
                url="https://flipkart.com/careers",
                required_skills="React, TypeScript, Python, SQL",
                match_score=0.82,
            ),
        ]
        db.add_all(opportunities)

        # ───────────────────────────────────────────────
        # 11. Study Plans
        # ───────────────────────────────────────────────
        plans = [
            StudyPlan(
                user_id=user.id,
                title="DBMS Mid-Sem Preparation Plan",
                target_date=now + timedelta(days=12),
                plan_json=json.dumps({
                    "weeks": [
                        {"week": 1, "topics": ["ER Diagrams", "Relational Model", "SQL Basics"], "hours": 10},
                        {"week": 2, "topics": ["Normalization", "Transactions", "Concurrency Control"], "hours": 12},
                    ],
                    "resources": ["Navathe Textbook Ch. 1-8", "Gate Smasher YouTube playlist"],
                }),
                status="active",
            ),
            StudyPlan(
                user_id=user.id,
                title="DSA Interview Prep – 30 Day Sprint",
                target_date=now + timedelta(days=30),
                plan_json=json.dumps({
                    "daily_target": 3,
                    "topics_order": ["Arrays", "Strings", "Linked Lists", "Trees", "Graphs", "DP", "Heaps", "Design"],
                    "total_problems": 90,
                }),
                status="active",
            ),
        ]
        db.add_all(plans)

        # ───────────────────────────────────────────────
        # 12. Projects
        # ───────────────────────────────────────────────
        projects = [
            Project(
                user_id=user.id,
                title="StudentLife OS – AI-Powered Student Copilot",
                description="Full-stack app with FastAPI backend, React frontend, OpenClaw AI agent, Gemini integration, and Telegram bot.",
                due_at=now + timedelta(days=45),
                status="in_progress",
            ),
            Project(
                user_id=user.id,
                title="Distributed Key-Value Store",
                description="Implement a Raft-consensus based KV store in Python. Supports leader election, log replication, and snapshots.",
                due_at=now + timedelta(days=60),
                status="planned",
            ),
        ]
        db.add_all(projects)

        # ───────────────────────────────────────────────
        # 13. Notes
        # ───────────────────────────────────────────────
        notes = [
            Note(
                user_id=user.id,
                title="DBMS: BCNF Decomposition Algorithm",
                content="1. Find an FD X→Y that violates BCNF\n2. Decompose R into R1(XY) and R2(R-Y)\n3. Repeat until all relations are in BCNF\n\nKey insight: BCNF decomposition is always lossless-join but may NOT preserve all FDs.",
                topics_json=json.dumps(["DBMS", "Normalization", "BCNF"]),
            ),
            Note(
                user_id=user.id,
                title="OS: Page Replacement Algorithms Comparison",
                content="FIFO: Simple but suffers Belady's anomaly\nLRU: Optimal among online algorithms, needs hardware support\nOptimal: Theoretical best, replaces page used farthest in future\n\nLRU approximation: Clock algorithm (second-chance).",
                topics_json=json.dumps(["OS", "Virtual Memory", "Page Replacement"]),
            ),
            Note(
                user_id=user.id,
                title="Interview Tip: STAR Method",
                content="Situation: Describe the context\nTask: What was your responsibility\nAction: What you specifically did\nResult: Quantifiable outcome\n\nAlways have 3-4 STAR stories ready for behavioral rounds.",
                topics_json=json.dumps(["Interview Prep", "Behavioral"]),
            ),
        ]
        db.add_all(notes)

        # ───────────────────────────────────────────────
        # 14. Study Materials
        # ───────────────────────────────────────────────
        materials = [
            StudyMaterial(
                user_id=user.id,
                title="Navathe DBMS Chapter 7-8 Summary",
                material_type="summary",
                content="Covers normalization from 1NF through BCNF with worked examples. Key takeaway: minimal cover of FDs before decomposition.",
                topics_json=json.dumps(["DBMS", "Normalization"]),
            ),
            StudyMaterial(
                user_id=user.id,
                title="Striver's SDE Sheet – Graph Section",
                material_type="resource",
                content="BFS, DFS, Dijkstra, Bellman-Ford, Floyd-Warshall, Topological Sort, MST (Prim's & Kruskal's). 25 problems total.",
                topics_json=json.dumps(["DSA", "Graphs"]),
            ),
        ]
        db.add_all(materials)

        # ───────────────────────────────────────────────
        # 15. Pending Approval Requests
        # ───────────────────────────────────────────────
        approvals = [
            ApprovalRequest(
                user_id=user.id,
                action_type="send_email_draft",
                description="Send drafted email reply to Prof. Sharma: 'Re: OS Lab Report Extension Request'",
                metadata_json=json.dumps({
                    "draft_id": "mock-draft-101",
                    "to": "prof.sharma@university.edu",
                    "subject": "Re: OS Lab Report Extension Request",
                    "body": "Dear Professor Sharma,\n\nThank you for considering my request. I have finished the kernel trace benchmarks and will submit the final PDF by tonight.\n\nSincerely,\nKriti",
                }),
                status="pending",
            ),
            ApprovalRequest(
                user_id=user.id,
                action_type="send_email_draft",
                description="Send email to Google Recruiter: 'Re: Summer Internship Follow-up'",
                metadata_json=json.dumps({
                    "draft_id": "mock-draft-102",
                    "to": "recruiter@google.com",
                    "subject": "Re: Summer Internship Follow-up",
                    "body": "Hello,\n\nThank you for the update on my application. I'm very excited about the opportunity and look forward to the next steps.\n\nBest regards,\nKriti",
                }),
                status="pending",
            ),
        ]
        db.add_all(approvals)

        db.commit()

        # ───────────────────────────────────────────────
        # Summary
        # ───────────────────────────────────────────────
        print("=" * 60)
        print(" [OK] Demo data seeded successfully for Kriti!")
        print("=" * 60)
        print(f" User:            Kriti (kriti@university.edu)")
        print(f" Telegram Name:   kriti")
        print(f" Profile:         3rd Year CSE @ NIT Warangal, 8.85 CGPA")
        print(f" Courses:         {len(courses)}")
        print(f" Calendar Events: {len(events)} (including 1 intentional conflict)")
        print(f" Tasks:           {len(tasks)}")
        print(f" Deadlines:       {len(deadlines)}")
        print(f" Assignments:     {len(assignments)}")
        print(f" Exams:           {len(exams)}")
        print(f" Study Sessions:  {len(sessions)}")
        print(f" DSA Problems:    {len(dsa_problems)} solved, {len(dsa_progress)} topic summaries")
        print(f" Opportunities:   {len(opportunities)}")
        print(f" Study Plans:     {len(plans)}")
        print(f" Projects:        {len(projects)}")
        print(f" Notes:           {len(notes)}")
        print(f" Study Materials: {len(materials)}")
        print(f" Approvals:       {len(approvals)} pending")
        print("=" * 60)

    finally:
        db.close()


if __name__ == "__main__":
    seed()
