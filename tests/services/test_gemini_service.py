import pytest
from app.integrations.gemini_client import GeminiClient
from app.services.gemini_service import GeminiService
from app.services.prompt_builder import redact_sensitive_data, build_minimal_profile_context
from app.services.schema_validation import validate_structured_output, extract_json_block
from app.schemas.gemini_schemas import ContentClassificationResult, ExtractedTaskItem


def test_redact_sensitive_data():
    raw = "My API key is api_key: 'sk-1234567890abcdef1234' and Authorization: Bearer abcdef1234567890abcdef1234567890"
    redacted = redact_sensitive_data(raw)
    assert "sk-1234567890abcdef1234" not in redacted
    assert "[REDACTED]" in redacted


def test_build_minimal_profile_context():
    profile = {
        "college": "MIT",
        "degree": "BS Computer Science",
        "year": 3,
        "target_roles": "Software Engineer, Backend",
        "skills": "Python, SQL, Algorithms",
        "available_study_hours": 4.0,
        "private_notes": "Very secret personal note",
    }
    context = build_minimal_profile_context(profile)
    assert context["education"] == "BS Computer Science (Year 3)"
    assert context["skills"] == "Python, SQL, Algorithms"
    assert "private_notes" not in context


def test_extract_json_block_and_validation():
    markdown_wrapped = """
    ```json
    {
      "trust_level": "untrusted",
      "category": "assignment_notice",
      "contains_actionable_items": true,
      "reasoning": "Assignment email with deadline"
    }
    ```
    """
    extracted = extract_json_block(markdown_wrapped)
    result = validate_structured_output(extracted, ContentClassificationResult)
    assert result.trust_level == "untrusted"
    assert result.category == "assignment_notice"
    assert result.contains_actionable_items is True


def test_schema_validation_error_on_invalid_data():
    with pytest.raises(ValueError, match="Schema validation failed"):
        validate_structured_output({"title": "Test", "confidence": "invalid_number"}, ExtractedTaskItem)


@pytest.mark.asyncio
async def test_gemini_service_extract_tasks_and_deadlines():
    service = GeminiService(client=GeminiClient(is_mock=True))
    result = await service.extract_tasks_and_deadlines(
        content="Assignment 2 is due next Tuesday at 11:59 PM. Please submit to Canvas."
    )
    assert len(result.tasks) >= 1
    assert result.tasks[0].title == "Complete Database Normalization Assignment"
    assert result.tasks[0].priority == "high"
    assert len(result.deadlines) >= 1
    assert result.deadlines[0].is_hard_deadline is True


@pytest.mark.asyncio
async def test_gemini_service_generate_study_plan():
    service = GeminiService(client=GeminiClient(is_mock=True))
    profile = {"degree": "CS", "year": 2, "skills": "Python", "available_study_hours": 3.0}
    plan = await service.generate_study_plan(profile=profile, tasks=[], calendar_events=[])
    assert plan.plan_title != ""
    assert len(plan.sessions) >= 1
    assert plan.total_study_minutes > 0


@pytest.mark.asyncio
async def test_gemini_service_analyze_opportunity():
    service = GeminiService(client=GeminiClient(is_mock=True))
    profile = {"skills": "Python, SQL, Git", "target_roles": "Backend Developer"}
    opp = await service.analyze_opportunity(profile=profile, job_description="Looking for Python and Docker engineer.")
    assert opp.match_score >= 0
    assert "Python" in opp.matched_skills
    assert opp.recommendation in ("strongly_apply", "apply", "prepare_first", "not_recommended")


@pytest.mark.asyncio
async def test_gemini_service_generate_morning_briefing():
    service = GeminiService(client=GeminiClient(is_mock=True))
    profile = {"degree": "Computer Science"}
    briefing = await service.generate_morning_briefing(
        student_name="Alex",
        profile=profile,
        tasks=[{"title": "OS Lecture"}],
        calendar_events=[]
    )
    assert "Alex" in briefing.greeting or "Good morning" in briefing.greeting
    assert len(briefing.top_priorities) >= 1


@pytest.mark.asyncio
async def test_gemini_service_classify_content():
    service = GeminiService(client=GeminiClient(is_mock=True))
    classification = await service.classify_content("Midterm exam scheduled for Friday.")
    assert classification.trust_level in ("trusted", "untrusted", "suspicious")
    assert classification.category in (
        "academic_announcement", "assignment_notice", "internship_opportunity", "personal_message", "spam_or_irrelevant"
    )
