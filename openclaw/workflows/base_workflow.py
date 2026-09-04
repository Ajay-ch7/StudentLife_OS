import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any
from sqlalchemy.orm import Session

from app.services.audit_service import AuditService
from openclaw.agent.student_life_agent import StudentLifeAgent

logger = logging.getLogger(__name__)


class BaseWorkflow(ABC):
    """Abstract base class for all autonomous student workflows in OpenClaw."""

    def __init__(self, name: str, agent: StudentLifeAgent | None = None) -> None:
        self.name = name
        self.agent = agent or StudentLifeAgent()

    @abstractmethod
    async def run(self, user_id: int, db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute the workflow lifecycle."""
        pass

    def generate_workflow_id(self) -> str:
        """Create a unique trace identifier for this workflow run."""
        return f"{self.name}-{uuid.uuid4().hex[:8]}"

    def log_workflow_start(self, db: Session, user_id: int, workflow_id: str, message: str) -> None:
        AuditService.log_user_activity(
            db=db,
            user_id=user_id,
            activity_type=f"{self.name}_started",
            message=message,
            metadata={"workflow_id": workflow_id},
        )

    def log_workflow_complete(
        self, db: Session, user_id: int, workflow_id: str, message: str, metadata: dict[str, Any] | None = None
    ) -> None:
        meta = {"workflow_id": workflow_id}
        if metadata:
            meta.update(metadata)
        AuditService.log_user_activity(
            db=db,
            user_id=user_id,
            activity_type=f"{self.name}_completed",
            message=message,
            metadata=meta,
        )
