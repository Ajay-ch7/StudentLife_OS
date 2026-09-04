"""
REST API endpoints for the Multi-Agent Orchestration Layer.

POST /api/v1/orchestrate         — Manually trigger an orchestrated event
GET  /api/v1/orchestrate/history — View recent orchestration decision logs
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.activity_log import ActivityLog
from app.models.student_profile import User
from app.schemas.orchestration_schemas import OrchestratorEvent, OrchestratorEventType, OrchestratedResult
from app.services.orchestrator import multi_agent_orchestrator

router = APIRouter()
logger = logging.getLogger(__name__)


class OrchestrateRequest(BaseModel):
    event_type: OrchestratorEventType
    payload: dict[str, Any] = {}
    user_id: int | None = None


class OrchestrateHistoryItem(BaseModel):
    id: int
    orchestration_id: str | None
    activity_type: str
    message: str
    metadata: dict[str, Any] | None
    created_at: str


@router.post("/orchestrate", response_model=OrchestratedResult)
async def trigger_orchestration(
    request: OrchestrateRequest,
    db: Session = Depends(get_db),
) -> OrchestratedResult:
    """
    Manually trigger a multi-agent orchestration event.
    Returns the full OrchestratedResult with decision, execution log, and status.
    """
    # Resolve user
    user_id = request.user_id
    if user_id is None:
        first_user = db.query(User).first()
        if not first_user:
            raise HTTPException(status_code=404, detail="No users found. Please onboard first.")
        user_id = first_user.id

    event = OrchestratorEvent(
        event_type=request.event_type,
        user_id=user_id,
        payload=request.payload,
    )

    try:
        result = await multi_agent_orchestrator.run(event, db)
        return result
    except Exception as exc:
        logger.error("Orchestration endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Orchestration failed: {exc}")


@router.get("/orchestrate/history")
def get_orchestration_history(
    limit: int = 20,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """
    Retrieve recent orchestration decision logs from activity_logs.
    Returns entries with activity_type in (orchestration_decision, orchestration_fallback, orchestration_action_executed).
    """
    entries = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.activity_type.in_([
                "orchestration_decision",
                "orchestration_fallback",
                "orchestration_action_executed",
            ])
        )
        .order_by(ActivityLog.id.desc())
        .limit(limit)
        .all()
    )
    result = []
    for e in entries:
        metadata = None
        if e.metadata_json:
            try:
                metadata = json.loads(e.metadata_json)
            except Exception:
                metadata = {"raw": e.metadata_json}
        result.append({
            "id": e.id,
            "orchestration_id": e.orchestration_id or (metadata or {}).get("orchestration_id"),
            "activity_type": e.activity_type,
            "message": e.message,
            "metadata": metadata,
            "created_at": e.created_at.isoformat(),
        })
    return result
