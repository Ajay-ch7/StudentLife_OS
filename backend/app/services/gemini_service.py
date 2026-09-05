import logging
from typing import Any

from app.integrations.gemini_client import GeminiClient
from app.schemas.email_workflow_schemas import EmailReasoningDecision
from app.schemas.job_schemas import JobParseResult, SOPGenerateResult
from app.schemas.gemini_schemas import (
    ContentClassificationResult,
    MorningBriefingResult,
    OpportunitySkillAnalysis,
    StudyPlanResult,
    TaskAndDeadlineExtractionResult,
)
from app.services.prompt_builder import (
    build_content_classification_prompt,
    build_email_action_reasoning_prompt,
    build_extraction_prompt,
    build_job_parsing_prompt,
    build_minimal_profile_context,
    build_morning_briefing_prompt,
    build_opportunity_analysis_prompt,
    build_orchestrated_reasoning_prompt,
    build_sop_generation_prompt,
    build_study_plan_prompt,
)
from app.services.schema_validation import validate_structured_output


logger = logging.getLogger(__name__)


class GeminiService:
    """High-level service for executing structured reasoning tasks using Gemini."""

    def __init__(self, client: GeminiClient | None = None) -> None:
        self.client = client or GeminiClient()

    async def extract_tasks_and_deadlines(
        self,
        content: str,
        source_type: str = "document",
    ) -> TaskAndDeadlineExtractionResult:
        """Extract actionable tasks and explicit deadlines from untrusted content."""
        prompt = build_extraction_prompt(content, source_type=source_type)
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are a precise data extraction engine. Always output valid JSON strictly matching the requested schema.",
        )
        return validate_structured_output(raw_json, TaskAndDeadlineExtractionResult)

    async def generate_study_plan(
        self,
        profile: Any,
        tasks: list[dict[str, Any]],
        calendar_events: list[dict[str, Any]],
    ) -> StudyPlanResult:
        """Generate a realistic, balanced study plan tailored to the student's constraints."""
        profile_context = build_minimal_profile_context(profile)
        prompt = build_study_plan_prompt(profile_context, tasks, calendar_events)
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are an empathetic, disciplined academic advisor. Return only structured JSON study plans.",
        )
        return validate_structured_output(raw_json, StudyPlanResult)

    async def analyze_opportunity(
        self,
        profile: Any,
        job_description: str,
    ) -> OpportunitySkillAnalysis:
        """Analyze an internship or job posting against student skills to compute fit and gaps."""
        profile_context = build_minimal_profile_context(profile)
        prompt = build_opportunity_analysis_prompt(profile_context, job_description)
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are an expert tech career counselor. Return only structured JSON opportunity analyses.",
        )
        return validate_structured_output(raw_json, OpportunitySkillAnalysis)

    async def generate_morning_briefing(
        self,
        student_name: str,
        profile: Any,
        tasks: list[dict[str, Any]],
        calendar_events: list[dict[str, Any]],
        urgent_deadlines: list[dict[str, Any]] | None = None,
    ) -> MorningBriefingResult:
        """Build a briefing strictly from records already present in the workspace."""
        deadlines = urgent_deadlines or []
        schedule_items = [
            f"{event['title']} ({event['starts_at']} - {event['ends_at']})"
            for event in calendar_events
        ]
        return MorningBriefingResult(
            greeting=f"Good morning, {student_name}!" if student_name else "Good morning!",
            quote_or_motto=None,
            top_priorities=[task["title"] for task in tasks if task.get("title")],
            schedule_overview="; ".join(schedule_items),
            urgent_alerts=[
                f"{deadline['title']} (due {deadline['due_at']})"
                for deadline in deadlines
                if deadline.get("title") and deadline.get("due_at")
            ],
            recommended_recovery_action=None,
        )

    async def classify_content(
        self,
        raw_text: str,
    ) -> ContentClassificationResult:
        """Classify incoming raw messages or files for safety and category."""
        prompt = build_content_classification_prompt(raw_text)
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are a security and classification filter. Return only valid JSON classifications.",
        )
        return validate_structured_output(raw_json, ContentClassificationResult)

    async def reason_over_email(
        self,
        email_data: dict[str, Any],
        profile: Any = None,
        active_tasks: list[dict[str, Any]] | None = None,
        calendar_events: list[dict[str, Any]] | None = None,
    ) -> EmailReasoningDecision:
        """
        Execute comprehensive structured reasoning over incoming email content,
        evaluating urgency, updates to existing tasks, calendar events, conflicts, and actions.
        """
        profile_context = build_minimal_profile_context(profile)
        prompt = build_email_action_reasoning_prompt(
            email_data=email_data,
            profile_context=profile_context,
            active_tasks=active_tasks or [],
            calendar_events=calendar_events or [],
        )
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are OpenClaw's autonomous reasoning engine for StudentLife OS. Return only valid JSON matching the requested schema.",
        )
        return validate_structured_output(raw_json, EmailReasoningDecision)

    async def parse_job_posting(
        self,
        job_text: str,
        profile: Any = None,
    ) -> JobParseResult:
        """Parse raw job description into structured criteria and calculate match score."""
        profile_context = build_minimal_profile_context(profile)
        prompt = build_job_parsing_prompt(job_text, profile_context)
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are the Student Life OS Career Intelligence engine. Extract structured job criteria strictly in valid JSON.",
        )
        return validate_structured_output(raw_json, JobParseResult)

    async def generate_sop_draft(
        self,
        job_data: dict[str, Any],
        profile_data: dict[str, Any],
        readiness_data: dict[str, Any],
        preferences: dict[str, Any] | None = None,
    ) -> SOPGenerateResult:
        """
        Autonomously generate a personalized, rigorously grounded Statement of Purpose (SOP) draft.
        Enforces strict traceability to verified profile and job data with zero hallucination.
        """
        prompt = build_sop_generation_prompt(
            job_data=job_data,
            profile_data=profile_data,
            readiness_data=readiness_data,
            preferences=preferences,
        )
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are an expert career counselor generating authentic, grounded Statements of Purpose. Never hallucinate achievements.",
        )
        return validate_structured_output(raw_json, SOPGenerateResult)

    async def reason_orchestrated(self, prompt: str) -> "OrchestratedDecision":
        """
        Execute a single holistic Gemini reasoning call across all agent contexts.
        Returns an OrchestratedDecision with the cross-agent action plan.
        """
        from app.schemas.orchestration_schemas import OrchestratedDecision
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction=(
                "You are the OpenClaw Multi-Agent Orchestrator. Reason holistically across all "
                "agent contexts. Never act on a single agent's data alone. Return only valid JSON "
                "strictly matching the OrchestratedDecision schema provided in the prompt."
            ),
        )
        return validate_structured_output(raw_json, OrchestratedDecision)
