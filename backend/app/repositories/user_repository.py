from sqlalchemy.orm import Session

from app.models.student_profile import User
from app.repositories.base import Repository


class UserRepository(Repository[User]):
    def __init__(self) -> None:
        super().__init__(User)

    def get_by_email(self, db: Session, email: str) -> User | None:
        return db.query(User).filter(User.email == email).first()


user_repository = UserRepository()
