from sqlalchemy.orm import Session

from app.models.task import Task
from app.repositories.base import Repository


class TaskRepository(Repository[Task]):
    def __init__(self) -> None:
        super().__init__(Task)

    def list_for_user(self, db: Session, user_id: int, *, limit: int = 100) -> list[Task]:
        return (
            db.query(Task)
            .filter(Task.user_id == user_id)
            .order_by(Task.deadline.asc(), Task.id.asc())
            .limit(limit)
            .all()
        )


task_repository = TaskRepository()
