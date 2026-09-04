import asyncio
import json
import logging
from typing import Any
import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class GeminiAPIError(Exception):
    """Raised when the Gemini API returns an error or fails retries."""
    pass


class GeminiClient:
    """Resilient client for interacting with the Google Gemini API with JSON mode and fallback mock capabilities."""

    def __init__(self, settings: Settings | None = None, is_mock: bool | None = None) -> None:
        self.settings = settings or get_settings()
        self.is_mock = is_mock if is_mock is not None else (
            self.settings.gemini_api_key in ("changeme", "", None) or getattr(self.settings, "app_env", "") == "test"
        )
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.settings.gemini_model}:generateContent"

    async def generate_json(
        self,
        prompt: str,
        system_instruction: str | None = None,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
    ) -> str:
        """Send a prompt to Gemini requesting structured JSON, with retry and backoff."""
        if self.is_mock:
            logger.info("Using mock Gemini response")
            return self._generate_mock_response(prompt)

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.settings.gemini_api_key,
        }

        payload: dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        backoff = initial_backoff
        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.settings.gemini_timeout_seconds) as client:
                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        json=payload,
                    )

                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        raise GeminiAPIError("No candidates returned from Gemini API")
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if not parts:
                        raise GeminiAPIError("Empty content parts in Gemini response")
                    return parts[0].get("text", "{}")

                # Handle rate limiting or server errors with backoff
                if response.status_code in (429, 500, 502, 503, 504):
                    logger.warning(
                        "Gemini API returned status %d (attempt %d/%d). Retrying in %.2fs...",
                        response.status_code,
                        attempt,
                        max_retries,
                        backoff,
                    )
                    if attempt == max_retries:
                        raise GeminiAPIError(
                            f"Gemini API failed with status {response.status_code}: {response.text}"
                        )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                else:
                    raise GeminiAPIError(
                        f"Gemini API client error {response.status_code}: {response.text}"
                    )

            except httpx.RequestError as exc:
                logger.warning(
                    "HTTP connection error contacting Gemini API (attempt %d/%d): %s",
                    attempt,
                    max_retries,
                    exc,
                )
                if attempt == max_retries:
                    raise GeminiAPIError(f"Network error contacting Gemini API: {exc}") from exc
                await asyncio.sleep(backoff)
                backoff *= 2

        raise GeminiAPIError("Maximum retries exceeded without response")

    def _generate_mock_response(self, prompt: str) -> str:
        """Deterministic mock JSON responses for testing and offline local execution."""
        prompt_lower = prompt.lower()

        if "extract all actionable tasks" in prompt_lower or "extraction engine" in prompt_lower:
            return json.dumps({
                "tasks": [
                    {
                        "title": "Complete Database Normalization Assignment",
                        "description": "Solve exercises 1-5 on 3NF and BCNF schemas",
                        "deadline": "2026-09-15T23:59:00Z",
                        "priority": "high",
                        "category": "assignment",
                        "estimated_effort_hours": 3.5,
                        "confidence": 0.95,
                    }
                ],
                "deadlines": [
                    {
                        "title": "DBMS Assignment Submission Deadline",
                        "due_at": "2026-09-15T23:59:00Z",
                        "source_context": "Due next Tuesday by 11:59 PM on Canvas",
                        "is_hard_deadline": True,
                        "confidence": 0.98,
                    }
                ],
                "summary": "Extracted 1 coursework assignment task and 1 submission deadline.",
            })

        if "daily study plan" in prompt_lower or "study advisor" in prompt_lower:
            return json.dumps({
                "plan_title": "Focused Rhythm: DBMS & DSA Prep",
                "daily_focus": "Master BCNF schema design and solve 2 Dynamic Programming problems",
                "sessions": [
                    {
                        "subject_or_task": "DBMS Theory & Exercises",
                        "duration_minutes": 90,
                        "target_objective": "Complete Questions 1 to 3 on 3NF/BCNF decomposition",
                        "recommended_time_of_day": "morning",
                        "rationale": "High cognitive load topic best tackled early in the day",
                    },
                    {
                        "subject_or_task": "DSA Practice (Trees & DP)",
                        "duration_minutes": 60,
                        "target_objective": "Implement Binary Tree Maximum Path Sum and review patterns",
                        "recommended_time_of_day": "afternoon",
                        "rationale": "Maintain problem-solving speed without exhausting study budget",
                    }
                ],
                "total_study_minutes": 150,
                "advisory_notes": [
                    "Take a 10-minute walk after the DBMS block.",
                    "Review memory diagrams before sleeping."
                ],
            })

        if "internship/job posting" in prompt_lower or "career mentor" in prompt_lower:
            return json.dumps({
                "matched_skills": ["Python", "FastAPI", "SQL", "Git"],
                "missing_skills": ["Docker", "Kubernetes", "Redis"],
                "match_score": 82,
                "recommendation": "apply",
                "summary": "Strong core alignment with backend requirements; missing containerization tools can be learned during onboarding.",
                "action_items": [
                    "Tailor resume to emphasize FastAPI and relational schema design experience.",
                    "Review basic Docker containerization concepts before interview."
                ],
            })

        if "morning briefing" in prompt_lower:
            return json.dumps({
                "greeting": "Good morning! Here is your daily rhythm.",
                "quote_or_motto": "Consistent daily execution compounds into remarkable mastery.",
                "top_priorities": [
                    "Finish DBMS Assignment questions 1-3",
                    "Attend 2:00 PM Operating Systems Lecture",
                    "Solve 1 DSA DP problem"
                ],
                "schedule_overview": "Light morning open window followed by 2:00 PM lecture and 5:00 PM study block.",
                "urgent_alerts": [
                    "DBMS Assignment due in 4 days"
                ],
                "recommended_recovery_action": None,
            })

        if "classify its trust level" in prompt_lower or "classification" in prompt_lower:
            return json.dumps({
                "trust_level": "untrusted",
                "category": "academic_announcement",
                "contains_actionable_items": True,
                "reasoning": "Standard academic assignment email containing specific deadlines.",
            })

        # Generic default
        return json.dumps({
            "status": "ok",
            "message": "Processed successfully",
            "details": "Default mock response",
        })
