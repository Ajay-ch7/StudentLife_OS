from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.student_profile import User


def get_current_user(db: Session = Depends(get_db)) -> User:
    user = db.query(User).order_by(User.id.asc()).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No user data is available")
    return user


def get_current_user_id(user: User = Depends(get_current_user)) -> int:
    return user.id