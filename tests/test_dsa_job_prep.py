import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app import models  # noqa: F401
from app.api.v1.dependencies import get_current_user_id
from app.db.database import Base, get_db
from app.main import app
from app.models.dsa_problem import DSAProblem
from app.models.student_profile import User
from app.services.dsa_service import DSAService


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionClass = sessionmaker(bind=engine)
    session = SessionClass()

    user = User(email="job_dsa_user@test.com", full_name="Job DSA Student", telegram_name="job_dsa")
    session.add(user)
    session.commit()
    session.refresh(user)

    user_id = user.id

    def override_get_db():
        db = SessionClass()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    yield session, user, TestClient(app)

    session.close()
    app.dependency_overrides.clear()


def test_ensure_job_applications_and_plans(test_db):
    db, user, client = test_db

    apps = DSAService.ensure_job_applications_and_plans(db, user.id)
    assert len(apps) >= 4

    summary = DSAService.get_job_applications_dsa_summary(db, user.id)
    assert len(summary) >= 4
    companies = {s["company"] for s in summary}
    assert "Google" in companies
    assert "Razorpay" in companies
    assert "Microsoft" in companies
    assert "Flipkart" in companies


def test_dynamic_dsa_matching_and_completion_percentage(test_db):
    db, user, client = test_db

    # Ensure job applications exist
    apps = DSAService.ensure_job_applications_and_plans(db, user.id)
    google_app = next(a for a in apps if "Google" in (a.notes or ""))

    # Before adding solved problems, google completion should be 0.0%
    plan_before = DSAService.get_job_dsa_plan(db, user.id, google_app.id)
    assert plan_before["completion_percentage"] == 0.0
    assert plan_before["solved_count"] == 0

    # Add a solved LeetCode problem that matches one in Google's plan ("Two Sum")
    solved1 = DSAProblem(
        user_id=user.id,
        title="Two Sum",
        topic="Arrays & Hashing",
        difficulty="Easy",
        solved_on=date.today(),
        leetcode_submission_id="sub_twosum_123",
    )
    db.add(solved1)
    db.commit()

    # Re-check plan
    plan_after = DSAService.get_job_dsa_plan(db, user.id, google_app.id)
    assert plan_after["solved_count"] == 1
    assert plan_after["completion_percentage"] > 0.0
    assert any(p["title"] == "Two Sum" and p["is_solved"] for p in plan_after["solved_problems"])


def test_dsa_job_applications_endpoints(test_db):
    db, user, client = test_db

    # Initialize data
    DSAService.ensure_job_applications_and_plans(db, user.id)

    # Test GET /api/v1/dsa/job-applications
    res = client.get("/api/v1/dsa/job-applications")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 4

    app_id = data[0]["application_id"]

    # Test GET /api/v1/dsa/job-applications/{id}/plan
    plan_res = client.get(f"/api/v1/dsa/job-applications/{app_id}/plan")
    assert plan_res.status_code == 200
    plan_data = plan_res.json()
    assert "planned_problems" in plan_data
    assert "solved_problems" in plan_data
    assert "remaining_problems" in plan_data
    assert "completion_percentage" in plan_data
