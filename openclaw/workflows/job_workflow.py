import logging
from typing import Any
from sqlalchemy.orm import Session

from app.schemas.job_schemas import JobProcessInput
from app.schemas.orchestration_schemas import OrchestratorEvent, OrchestratorEventType
from app.services.job_agent_service import job_agent_service
from app.services.orchestrator import multi_agent_orchestrator
from openclaw.workflows.base_workflow import BaseWorkflow

logger = logging.getLogger(__name__)


class AutonomousJobWorkflow(BaseWorkflow):
    """
    OpenClaw autonomous workflow that processes incoming job opportunities,
    evaluates DSA role readiness, generates personalized SOP drafts, and logs
    every decision to activity_logs.
    """

    def __init__(self, agent=None) -> None:
        super().__init__(name="autonomous_job_processing", agent=agent)

    async def run(self, user_id: int, db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        job_text = payload.get("job_text") or payload.get("opportunity_text") or ""
        workflow_id = self.generate_workflow_id()

        self.log_workflow_start(db, user_id, workflow_id, "Processing career opportunity & autonomous SOP drafting")

        if not job_text:
            return {
                "workflow_id": workflow_id,
                "status": "error",
                "error": "No job description text provided to evaluate",
            }

        job_input = JobProcessInput(
            job_text=job_text,
            company=payload.get("company"),
            title=payload.get("title") or payload.get("role_title"),
            tone_preference=payload.get("tone_preference", "formal"),
            specific_points=payload.get("specific_points"),
            source=payload.get("source", "openclaw_agent"),
            url=payload.get("url"),
        )

        # Orchestrator intercept: cross-agent context before job posting
        try:
            orch_event = OrchestratorEvent(
                event_type=OrchestratorEventType.NEW_JOB_POSTING,
                user_id=user_id,
                payload={"job_text": job_text, "company": payload.get("company"), "title": payload.get("title")},
                workflow_id=f"orch-job-{workflow_id}",
            )
            await multi_agent_orchestrator.run(orch_event, db)
        except Exception as orch_exc:
            logger.warning("Orchestrator intercept failed in Job workflow (fallback): %s", orch_exc)

        job_record = await job_agent_service.process_job_posting(db, user_id, job_input)

        self.log_workflow_complete(
            db,
            user_id,
            workflow_id,
            f"Autonomous Job Workflow completed for {job_record.company}: match {job_record.match_score}%, readiness {job_record.readiness_score}%",
            metadata={
                "job_id": job_record.id,
                "company": job_record.company,
                "role": job_record.title,
                "sop_status": job_record.sop_status,
                "readiness_score": job_record.readiness_score,
            },
        )

        return {
            "workflow_id": workflow_id,
            "status": "completed",
            "job_id": job_record.id,
            "company": job_record.company,
            "title": job_record.title,
            "match_score": job_record.match_score,
            "readiness_score": job_record.readiness_score,
            "role_match": job_record.role_match,
            "sop_status": job_record.sop_status,
            "has_sop_draft": bool(job_record.sop_draft),
        }
