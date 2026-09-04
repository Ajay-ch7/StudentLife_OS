from typing import Any
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.services.inbox_service import InboxService

router = APIRouter(prefix="/inbox", tags=["inbox"])
inbox_service = InboxService()


class InboxProcessRequest(BaseModel):
    content: str = Field(..., min_length=5, description="Raw text of email, document snippet, or chat message")
    source_type: str = Field("email", description="Source category (e.g. email, syllabus, announcement, chat)")
    metadata: dict[str, Any] | None = None


class InboxProcessResponse(BaseModel):
    workflow_id: str
    status: str
    summary: str
    total_extracted: int
    tasks_created: list[dict[str, Any]]
    skipped_duplicates: list[str]
    detected_conflicts: list[dict[str, Any]]
    dry_run: bool


@router.post("/process", response_model=InboxProcessResponse, status_code=status.HTTP_200_OK)
async def process_inbox_content(
    payload: InboxProcessRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> InboxProcessResponse:
    """Ingest untrusted content, extract structured tasks, check conflicts, and persist to SQLite."""
    result = await inbox_service.process_content(
        db=db,
        user_id=user_id,
        content=payload.content,
        source_type=payload.source_type,
        source_metadata=payload.metadata,
        dry_run=False,
    )
    return InboxProcessResponse(**result)


@router.post("/preview", response_model=InboxProcessResponse, status_code=status.HTTP_200_OK)
async def preview_inbox_extraction(
    payload: InboxProcessRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> InboxProcessResponse:
    """Extract tasks and check conflicts in dry-run mode without persisting changes."""
    result = await inbox_service.process_content(
        db=db,
        user_id=user_id,
        content=payload.content,
        source_type=payload.source_type,
        source_metadata=payload.metadata,
        dry_run=True,
    )
    return InboxProcessResponse(**result)
