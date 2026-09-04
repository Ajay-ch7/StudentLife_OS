import json
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.models.application import Application
from app.models.opportunity import Opportunity
from app.models.student_profile import StudentProfile
from app.schemas.opportunities import ApplicationCreate, OpportunityCreate
from app.services.approval_service import ApprovalService

router = APIRouter(tags=["opportunities"])


def _skills(value: str | None) -> set[str]:
    return {skill.strip().lower() for skill in (value or "").split(",") if skill.strip()}


@router.get("/opportunities")
def list_opportunities(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    return db.query(Opportunity).filter(Opportunity.user_id == user_id).order_by(Opportunity.match_score.desc().nullslast()).all()


@router.post("/opportunities")
def create_opportunity(payload: OpportunityCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user_id).first()
    required = {skill.strip() for skill in payload.required_skills if skill.strip()}
    matched = len({skill.lower() for skill in required} & _skills(profile.skills if profile else None))
    score = round(matched / len(required) * 100, 2) if required else 0.0
    item = Opportunity(user_id=user_id, required_skills=", ".join(sorted(required)), match_score=score, **payload.model_dump(exclude={"required_skills"}))
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.get("/opportunities/{opportunity_id}/match")
def opportunity_match(opportunity_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    item = db.query(Opportunity).filter(Opportunity.id == opportunity_id, Opportunity.user_id == user_id).first()
    if item is None: raise HTTPException(status_code=404, detail="Opportunity not found")
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user_id).first()
    required = _skills(item.required_skills)
    matched = sorted(required & _skills(profile.skills if profile else None))
    return {"opportunity_id": item.id, "match_score": item.match_score or 0, "matched_skills": matched, "skill_gaps": sorted(required - set(matched))}


@router.get("/applications")
def list_applications(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    return db.query(Application).filter(Application.user_id == user_id).order_by(Application.created_at.desc()).all()


@router.put("/applications/{application_id}/status")
def update_application_status(application_id: int, status: str, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    if status not in {"saved", "awaiting_approval", "submitted", "interview", "rejected", "offer"}:
        raise HTTPException(status_code=422, detail="Invalid application status")
    item = db.query(Application).filter(Application.id == application_id, Application.user_id == user_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Application not found")
    item.status = status; db.commit(); db.refresh(item)
    return item


@router.post("/applications")
def create_application(payload: ApplicationCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    item = db.query(Opportunity).filter(Opportunity.id == payload.opportunity_id, Opportunity.user_id == user_id).first()
    if item is None: raise HTTPException(status_code=404, detail="Opportunity not found")
    application = Application(user_id=user_id, **payload.model_dump())
    db.add(application); db.commit(); db.refresh(application)
    return application


@router.post("/applications/{application_id}/submit")
def submit_application(application_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    application = db.query(Application).filter(Application.id == application_id, Application.user_id == user_id).first()
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    request = ApprovalService.create(
        db, user_id, "submit_application", f"Submit application {application.id}",
        json.dumps({"application_id": application.id, "opportunity_id": application.opportunity_id}),
    )
    application.status = "awaiting_approval"
    db.commit()
    return {"status": "approval_required", "approval_request_id": request.id, "application_id": application.id}