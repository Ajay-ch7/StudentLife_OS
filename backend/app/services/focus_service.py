from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.study_session import StudySession


class FocusService:
    @staticmethod
    def start(db: Session, session: StudySession, started_at: datetime | None = None) -> StudySession:
        if session.status not in {"planned", "missed"}:
            raise ValueError(f"Session is already {session.status}")
        session.actual_start = started_at or datetime.now(timezone.utc)
        session.status = "in_progress"
        db.commit(); db.refresh(session)
        return session

    @staticmethod
    def end(db: Session, session: StudySession, ended_at: datetime | None = None) -> StudySession:
        if session.status != "in_progress" or session.actual_start is None:
            raise ValueError("Session must be started before it can end")
        end = ended_at or datetime.now(timezone.utc)
        if end <= session.actual_start:
            raise ValueError("actual end must be after actual start")
        session.actual_end = end
        session.status = "completed"
        db.commit(); db.refresh(session)
        return session

    @staticmethod
    def missed(db: Session, user_id: int, now: datetime | None = None) -> list[StudySession]:
        current = now or datetime.now(timezone.utc)
        sessions = db.query(StudySession).filter(
            StudySession.user_id == user_id,
            StudySession.status == "planned",
            StudySession.planned_end < current,
        ).all()
        for session in sessions:
            session.status = "missed"
        if sessions:
            db.commit()
        return sessions