from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.seed import seed_default_user
from app.models.student_profile import User


def get_current_user(db: Session = Depends(get_db)) -> User:
    return seed_default_user(db)


def get_current_user_id(user: User = Depends(get_current_user)) -> int:
    return user.id