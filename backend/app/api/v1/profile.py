from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user
from app.db.database import get_db
from app.models.student_profile import User
from app.schemas.common import ProfileEnvelope, ProfileInput
from app.services.profile_service import save_profile

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileEnvelope)
def get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProfileEnvelope:
    db.refresh(user)
    return ProfileEnvelope(user=user, profile=user.profile)


@router.get("/{profile_id}", response_model=ProfileEnvelope)
def get_profile_by_id(profile_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProfileEnvelope:
    if user.profile is None or user.profile.id != profile_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return ProfileEnvelope(user=user, profile=user.profile)


@router.post("", response_model=ProfileEnvelope, status_code=status.HTTP_201_CREATED)
def create_profile(payload: ProfileInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProfileEnvelope:
    profile = save_profile(db, user, payload)
    return ProfileEnvelope(user=user, profile=profile)


@router.put("/{profile_id}", response_model=ProfileEnvelope)
def update_profile(profile_id: int, payload: ProfileInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProfileEnvelope:
    if user.profile is None or user.profile.id != profile_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    profile = save_profile(db, user, payload)
    return ProfileEnvelope(user=user, profile=profile)