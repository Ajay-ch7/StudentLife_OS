from sqlalchemy.orm import Session

from app.models.student_profile import StudentProfile
from app.repositories.base import Repository


class ProfileRepository(Repository[StudentProfile]):
    def __init__(self) -> None:
        super().__init__(StudentProfile)

    def get_for_user(self, db: Session, user_id: int) -> StudentProfile | None:
        return db.query(StudentProfile).filter(StudentProfile.user_id == user_id).first()


profile_repository = ProfileRepository()
