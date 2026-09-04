import csv
import io
from collections import Counter
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.models.dsa_problem import DSAProblem
from app.models.dsa_progress import DSAProgress


class DSAService:
    @staticmethod
    def summary(db: Session, user_id: int) -> dict:
        items = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).all()
        days = {item.solved_on for item in items}
        streak = 0; cursor = date.today()
        while cursor in days:
            streak += 1; cursor -= timedelta(days=1)
        topics = Counter(item.topic for item in items)
        return {"total": len(items), "streak": streak, "topics": dict(topics), "weak_topics": sorted(topic for topic, count in topics.items() if count < 3)}

    @staticmethod
    def sync_progress(db: Session, user_id: int) -> None:
        items = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).all()
        grouped: dict[str, list[DSAProblem]] = {}
        for item in items: grouped.setdefault(item.topic, []).append(item)
        for topic, values in grouped.items():
            progress = db.query(DSAProgress).filter(DSAProgress.user_id == user_id, DSAProgress.topic == topic).first()
            if progress is None:
                progress = DSAProgress(user_id=user_id, topic=topic); db.add(progress)
            progress.solved_count = len(values)
            progress.revision_count = sum(item.needs_revision for item in values)
        db.commit()

    @staticmethod
    def import_csv(db: Session, user_id: int, content: str) -> int:
        rows = csv.DictReader(io.StringIO(content))
        required = {"title", "topic", "difficulty", "solved_on"}
        if not rows.fieldnames or not required.issubset(set(rows.fieldnames)):
            raise ValueError("CSV requires title, topic, difficulty, and solved_on columns")
        items = [DSAProblem(user_id=user_id, title=row["title"].strip(), topic=row["topic"].strip(), difficulty=row["difficulty"].strip(), attempts=int(row.get("attempts") or 1), solved_on=date.fromisoformat(row["solved_on"]), needs_revision=str(row.get("needs_revision", "false")).lower() == "true") for row in rows]
        db.add_all(items); db.commit(); DSAService.sync_progress(db, user_id)
        return len(items)