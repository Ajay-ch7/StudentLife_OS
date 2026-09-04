from sqlalchemy.orm import Session

from app.models.student_profile import StudentProfile, User
from app.repositories.profile_repository import profile_repository
from app.schemas.common import ProfileInput


def save_profile(db: Session, user: User, payload: ProfileInput) -> StudentProfile:
    values = payload.model_dump(exclude_unset=True)
    full_name = values.pop("full_name", None)
    if full_name is not None:
        user.full_name = full_name.strip()

    profile = profile_repository.get_for_user(db, user.id)
    if profile is None:
        profile = profile_repository.create(db, user_id=user.id, **values)
    else:
        for field, value in values.items():
            setattr(profile, field, value)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile