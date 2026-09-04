import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.approval_request import ApprovalRequest
from app.services.audit_service import AuditService


class ApprovalService:
    """Own approval state transitions and keep them auditable."""

    @staticmethod
    def create(
        db: Session,
        user_id: int,
        action_type: str,
        description: str,
        metadata_json: str | None = None,
        expires_at: datetime | None = None,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            user_id=user_id,
            action_type=action_type,
            description=description,
            metadata_json=metadata_json,
            expires_at=expires_at,
            status="pending",
        )
        db.add(request)
        db.commit()
        db.refresh(request)
        AuditService.log_user_activity(
            db, user_id, "approval_requested", f"Approval requested for {action_type}: {description}", {"request_id": request.id}
        )
        return request

    @staticmethod
    def expire_if_needed(db: Session, request: ApprovalRequest) -> ApprovalRequest:
        if request.status == "pending" and request.expires_at is not None:
            now = datetime.now(timezone.utc)
            expires_at = request.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                request.status = "expired"
                request.resolved_at = now
                db.commit()
                db.refresh(request)
        return request

    @staticmethod
    def resolve(db: Session, request: ApprovalRequest, status: str, reason: str | None = None) -> ApprovalRequest:
        ApprovalService.expire_if_needed(db, request)
        if request.status != "pending":
            raise ValueError(f"Approval request is already {request.status}")
        request.status = status
        request.resolved_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(request)
        AuditService.log_user_activity(
            db,
            request.user_id,
            f"approval_{status}",
            f"Approval {status}: {request.action_type}",
            {"request_id": request.id, "reason": reason} if reason else {"request_id": request.id},
        )
        return request

    @staticmethod
    def record_result(db: Session, request: ApprovalRequest, result: Any) -> ApprovalRequest:
        request.result_json = json.dumps(result, default=str)
        db.commit()
        db.refresh(request)
        return request

    @staticmethod
    def retry(db: Session, request: ApprovalRequest) -> ApprovalRequest:
        if request.status not in {"rejected", "expired"}:
            raise ValueError("Only rejected or expired approvals can be retried")
        return ApprovalService.create(
            db=db,
            user_id=request.user_id,
            action_type=request.action_type,
            description=request.description,
            metadata_json=request.metadata_json,
            expires_at=request.expires_at,
        )