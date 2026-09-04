from datetime import date
from fastapi import File, UploadFile, HTTPException
from typing import Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.models.dsa_problem import DSAProblem
from app.schemas.dsa import DSAImport, DSAProblemCreate
from app.services.dsa_service import DSAService

router = APIRouter(prefix="/dsa", tags=["dsa"])


@router.get("")
def progress(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> dict:
    items = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).order_by(DSAProblem.solved_on.desc()).all()
    return {"problems": items, **DSAService.summary(db, user_id)}


@router.post("/problems")
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