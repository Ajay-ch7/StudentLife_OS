from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base_models import BaseEntity


class User(BaseEntity):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    profile: Mapped["StudentProfile"] = relationship(back_populates="user")


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    college: Mapped[str | None] = mapped_column(String(255), nullable=True)
    degree: Mapped[str | None] = mapped_column(String(255), nullable=True)
    year: Mapped[int | None] = mapped_column(nullable=True)
    cgpa: Mapped[float | None] = mapped_column(nullable=True)
    target_roles: Mapped[str | None] = mapped_column(String(500), nullable=True)
    target_companies: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped[User] = relationship(back_populates="profile")
