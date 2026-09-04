import pytest
from app.core.config import Settings
from app.integrations.gemini_client import GeminiClient, GeminiAPIError
from app.services.schema_validation import validate_structured_output
from app.schemas.gemini_schemas import TaskAndDeadlineExtractionResult


@pytest.mark.asyncio
async def test_mock_gemini_client_task_extraction():
    settings = Settings(gemini_api_key="changeme", app_env="test")
    client = GeminiClient(settings=settings, is_mock=True)

    result_json = await client.generate_json(
        prompt="Please extract all actionable tasks from this syllabus"
    )
    assert result_json is not None
    result = validate_structured_output(result_json, TaskAndDeadlineExtractionResult)
    assert len(result.tasks) >= 1
    assert result.tasks[0].title == "Complete Database Normalization Assignment"
    assert result.tasks[0].confidence >= 0.9
    assert len(result.deadlines) >= 1


@pytest.mark.asyncio
async def test_gemini_client_mock_study_plan():
    client = GeminiClient(is_mock=True)
    result_json = await client.generate_json(prompt="Generate a daily study plan for today")
    assert "DBMS Theory & Exercises" in result_json
    assert "DSA Practice" in result_json


@pytest.mark.asyncio
async def test_gemini_client_mock_opportunity():
    client = GeminiClient(is_mock=True)
    result_json = await client.generate_json(prompt="Analyze this internship/job posting")
    assert "Python" in result_json
    assert "match_score" in result_json
