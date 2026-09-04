from datetime import date
from fastapi import File, UploadFile, HTTPException
from typing import Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.models.dsa_problem import DSAProblem
from app.schemas.dsa import DSAImport, DSAProblemCreate, DSAProblemResponse
from app.services.dsa_service import DSAService

router = APIRouter(prefix="/dsa", tags=["dsa"])


@router.get("")
def progress(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    items = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).order_by(DSAProblem.solved_on.desc()).all()
    problems_data = [
        {
            "id": p.id,
            "user_id": p.user_id,
            "title": p.title,
            "topic": p.topic,
            "difficulty": p.difficulty,
            "attempts": p.attempts,
            "solved_on": p.solved_on.isoformat() if p.solved_on else None,
            "needs_revision": p.needs_revision,
        }
        for p in items
    ]
    return {"problems": problems_data, **DSAService.summary(db, user_id)}


@router.post("/problems", response_model=DSAProblemResponse)
def create_problem(payload: DSAProblemCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    item = DSAProblem(user_id=user_id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    DSAService.sync_progress(db, user_id)
    return item


@router.post("/import")
def import_problems(payload: DSAImport, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    items = [DSAProblem(user_id=user_id, **problem.model_dump()) for problem in payload.problems]
    db.add_all(items); db.commit()
    DSAService.sync_progress(db, user_id)
    return {"imported": len(items)}


@router.post("/import/csv")
async def import_csv(file: UploadFile = File(...), user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="A CSV file is required")
    try:
        count = DSAService.import_csv(db, user_id, (await file.read()).decode("utf-8", errors="replace"))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"imported": count}


@router.put("/problems/{problem_id}/revision")
def set_revision(problem_id: int, needs_revision: bool, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Any:
    item = db.query(DSAProblem).filter(DSAProblem.id == problem_id, DSAProblem.user_id == user_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Problem not found")
    item.needs_revision = needs_revision; db.commit(); DSAService.sync_progress(db, user_id)
    return item


@router.get("/recommendations")
def recommendations(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    items = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).all()
    summary = DSAService.summary(db, user_id)
    return {"topics": summary["weak_topics"], "recommendation": f"Practice one problem in {summary['weak_topics'][0]}." if summary["weak_topics"] else "Keep your current rhythm."}


@router.post("/leetcode/sync")
async def sync_leetcode(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    from app.services.leetcode_watcher_service import leetcode_watcher_service
    res = await leetcode_watcher_service.check_user_leetcode_updates(db, user_id)
    return res


@router.get("/job-applications")
def get_job_applications_dsa_summary(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[dict]:
    return DSAService.get_job_applications_dsa_summary(db, user_id)


@router.get("/job-applications/{application_id}/plan")
def get_job_dsa_plan(application_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    plan = DSAService.get_job_dsa_plan(db, user_id, application_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Job application DSA plan not found")
    return plan


@router.get("/leetcode/status")
def leetcode_status(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    from app.models.leetcode_state import LeetCodeState
    from app.services.leetcode_watcher_service import leetcode_watcher_service

    username = leetcode_watcher_service.get_configured_username(db, user_id)
    state = db.query(LeetCodeState).filter(LeetCodeState.user_id == user_id).first()
    if not state:
        return {
            "username": username,
            "has_state": False,
            "total_solved": 0,
            "easy_solved": 0,
            "medium_solved": 0,
            "hard_solved": 0,
            "streak": 0,
            "active_days": 0,
            "ranking": None,
            "last_polled_at": None,
        }

    return {
        "username": state.leetcode_username,
        "has_state": True,
        "total_solved": state.total_solved,
        "easy_solved": state.easy_solved,
        "medium_solved": state.medium_solved,
        "hard_solved": state.hard_solved,
        "streak": state.streak,
        "active_days": state.active_days,
        "ranking": state.ranking,
        "last_submission_id": state.last_submission_id,
        "last_polled_at": state.last_polled_at.isoformat() if state.last_polled_at else None,
    }