from sqlalchemy.orm import Session

from app.models.student_profile import User

DEFAULT_USER_EMAIL = "student@example.com"


def seed_default_user(db: Session) -> User:
    user = db.query(User).filter(User.email == DEFAULT_USER_EMAIL).first()
    if user is None:
        user = User(email=DEFAULT_USER_EMAIL, full_name="Student")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
