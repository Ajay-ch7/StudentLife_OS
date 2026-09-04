import logging
from typing import Any

from app.integrations.gemini_client import GeminiClient
from app.schemas.email_workflow_schemas import EmailReasoningDecision
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
    build_minimal_profile_context,
    build_morning_briefing_prompt,
    build_opportunity_analysis_prompt,
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
    ) -> MorningBriefingResult:
        """Generate a focused morning briefing summary for the day."""
        profile_context = build_minimal_profile_context(profile)
        prompt = build_morning_briefing_prompt(student_name, profile_context, tasks, calendar_events)
        raw_json = await self.client.generate_json(
            prompt=prompt,
            system_instruction="You are the Student Life OS assistant. Return only concise, high-impact morning briefings in valid JSON.",
        )
        return validate_structured_output(raw_json, MorningBriefingResult)

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

