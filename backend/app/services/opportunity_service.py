from typing import Any

from sqlalchemy.orm import Session

from app.integrations.opportunity_adapter import CuratedOpportunityAdapter
from app.models.opportunity import Opportunity
from app.models.student_profile import StudentProfile


class OpportunityService:
    @staticmethod
    def score(profile: StudentProfile | None, required_skills: list[str]) -> tuple[float, list[str], list[str]]:
        current = {item.strip().lower() for item in (profile.skills if profile else "").split(",") if item.strip()}
        required = {item.strip() for item in required_skills if item.strip()}
        matched = sorted(item for item in required if item.lower() in current)
        gaps = sorted(required - set(matched))
        return (round(len(matched) / len(required) * 100, 2) if required else 0.0, matched, gaps)

    @staticmethod
    def curated_for_user(db: Session, user_id: int, query: str = "software", limit: int = 10) -> list[Opportunity]:
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == user_id).first()
        records = []
        for item in CuratedOpportunityAdapter().search(query, limit):
            score, _, _ = OpportunityService.score(profile, item["required_skills"])
            record = Opportunity(user_id=user_id, title=item["title"], company=item["company"], description=item["description"], required_skills=", ".join(item["required_skills"]), source=item["source"], match_score=score)
            db.add(record); records.append(record)
        if records:
            db.commit()
            for record in records: db.refresh(record)
        return records