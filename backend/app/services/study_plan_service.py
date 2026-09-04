import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.calendar_event import CalendarEvent
from app.models.study_plan import StudyPlan
from app.models.study_session import StudySession


class StudyPlanService:
    @staticmethod
    def validate_sessions(sessions: list[StudySession]) -> None:
        ordered = sorted(sessions, key=lambda item: item.planned_start)
        for session in ordered:
            if session.planned_end <= session.planned_start:
                raise ValueError("study session must end after it starts")
        for previous, current in zip(ordered, ordered[1:]):
            if current.planned_start < previous.planned_end:
                raise ValueError("study sessions overlap")

    @staticmethod
    def persist(db: Session, user_id: int, title: str, sessions: list[StudySession], target_date: datetime | None = None) -> StudyPlan:
        StudyPlanService.validate_sessions(sessions)
        plan = StudyPlan(user_id=user_id, title=title, target_date=target_date, plan_json=json.dumps({"session_ids": [item.id for item in sessions]}), status="generated")
        db.add(plan); db.commit(); db.refresh(plan)
        return plan

    @staticmethod
    def schedule(db: Session, user_id: int, sessions: list[StudySession]) -> list[CalendarEvent]:
        StudyPlanService.validate_sessions(sessions)
        events = [CalendarEvent(user_id=user_id, title=f"Study: {item.topic}", starts_at=item.planned_start, ends_at=item.planned_end, event_type="study", task_id=item.task_id) for item in sessions]
        db.add_all(events); db.commit()
        return events