from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.student_profile import User
from app.models.study_session import StudySession
from app.services.dsa_service import DSAService
from app.services.study_plan_service import StudyPlanService
from openclaw.workflows.end_of_day_review import EndOfDayReviewWorkflow


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user = User(email="phase@example.com", full_name="Phase Tester")
    db.add(user)
    db.commit()
    db.refresh(user)
    yield db, user
    db.close()


def test_study_plan_persists_and_schedules_without_overlap(session):
    db, user = session
    start = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
    study = StudySession(user_id=user.id, topic="Algorithms", planned_start=start, planned_end=start + timedelta(hours=1))
    db.add(study)
    db.commit()
    db.refresh(study)

    plan = StudyPlanService.persist(db, user.id, "Algorithms sprint", [study])
    events = StudyPlanService.schedule(db, user.id, [study])

    assert plan.status == "generated"
    assert plan.plan == {"session_ids": [study.id]}
    assert events[0].event_type == "study"


def test_study_plan_rejects_overlapping_sessions(session):
    db, user = session
    start = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
    sessions = [
        StudySession(user_id=user.id, topic="A", planned_start=start, planned_end=start + timedelta(hours=1)),
        StudySession(user_id=user.id, topic="B", planned_start=start + timedelta(minutes=30), planned_end=start + timedelta(hours=2)),
    ]
    with pytest.raises(ValueError, match="overlap"):
        StudyPlanService.validate_sessions(sessions)


def test_dsa_csv_import_syncs_topic_progress(session):
    db, user = session
    count = DSAService.import_csv(
        db,
        user.id,
        "title,topic,difficulty,solved_on,attempts,needs_revision\nTwo Sum,Arrays,Easy,2026-09-04,1,false\nGraph Paths,Graphs,Medium,2026-09-04,2,true\n",
    )
    assert count == 2
    assert DSAService.summary(db, user.id)["total"] == 2


@pytest.mark.asyncio
async def test_missed_focus_session_is_marked_missed(session):
    db, user = session
    now = datetime.now(timezone.utc)
    study = StudySession(user_id=user.id, topic="Recovery", planned_start=now - timedelta(hours=2), planned_end=now - timedelta(hours=1))
    db.add(study)
    db.commit()

    workflow = EndOfDayReviewWorkflow()
    res = await workflow.run(user.id, db)
    assert res["missed_session_ids"] == [study.id]
    assert db.get(StudySession, study.id).status == "missed"
