from datetime import datetime

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.student_profile import StudentProfile, User
from app.models.task import Task
from app.repositories.profile_repository import ProfileRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository


def test_schema_contains_phase_one_tables() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    assert set(inspect(engine).get_table_names()) == {
        "activity_logs",
        "agent_actions",
        "approval_requests",
        "applications",
        "assignments",
        "calendar_events",
        "courses",
        "deadlines",
        "dsa_problems",
        "dsa_progress",
        "job_dsa_plan_problems",
        "leetcode_state",
        "email_messages",
        "exams",
        "opportunities",
        "notes",
        "projects",
        "student_profiles",
        "study_materials",
        "study_plans",
        "study_sessions",
        "tasks",
        "users",
    }


def test_user_profile_and_task_repositories() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user_repository = UserRepository()
    profile_repository = ProfileRepository()
    task_repository = TaskRepository()

    user = user_repository.create(session, email="student@example.com", full_name="Student")
    profile_repository.create(session, user_id=user.id, college="Example University")
    task_repository.create(
        session,
        user_id=user.id,
        title="Submit assignment",
        deadline=datetime(2026, 9, 10),
    )

    assert user_repository.get_by_email(session, "student@example.com") is not None
    assert profile_repository.get_for_user(session, user.id).college == "Example University"
    assert [task.title for task in task_repository.list_for_user(session, user.id)] == [
        "Submit assignment"
    ]
    session.close()
