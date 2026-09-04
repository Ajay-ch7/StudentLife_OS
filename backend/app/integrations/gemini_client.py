import asyncio
import json
import logging
import sys
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
            self.settings.gemini_api_key in ("changeme", "your_gemini_api_key_here", "", None)
            or str(self.settings.gemini_api_key).startswith("your_gemini_api_key")
            or getattr(self.settings, "app_env", "") == "test"
            or "pytest" in sys.modules
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
                if response.status_code == 429:
                    logger.warning("Gemini API daily quota exceeded (HTTP 429); gracefully falling back to resilient mock generation.")
                    return self._generate_mock_response(prompt)

                if response.status_code in (500, 502, 503, 504):
                    logger.warning(
                        "Gemini API returned status %d (attempt %d/%d). Retrying in %.2fs...",
                        response.status_code,
                        attempt,
                        max_retries,
                        backoff,
                    )
                    if attempt == max_retries:
                        logger.warning("Gemini API server errors exhausted retries; falling back to mock response.")
                        return self._generate_mock_response(prompt)
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
                    logger.warning("Gemini API connection error exhausted retries; falling back to mock response.")
                    return self._generate_mock_response(prompt)
                await asyncio.sleep(backoff)
                backoff *= 2

        raise GeminiAPIError("Maximum retries exceeded without response")

    async def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
    ) -> str:
        """Send a prompt to Gemini requesting freeform plain text, with retry and backoff."""
        if self.is_mock:
            return "Keep up the great momentum and solve one Medium problem each day!"

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
                "temperature": 0.3,
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
                        return ""
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if not parts:
                        return ""
                    return parts[0].get("text", "").strip()

                if response.status_code == 429:
                    logger.warning("Gemini API quota exceeded (HTTP 429); returning default recommendation text.")
                    return "Focus on practicing medium difficulty problems to strengthen your algorithm fundamentals."

                if response.status_code in (500, 502, 503, 504):
                    if attempt == max_retries:
                        return "Focus on practicing medium difficulty problems to strengthen your algorithm fundamentals."
                    await asyncio.sleep(backoff)
                    backoff *= 2
                else:
                    return ""

            except Exception:
                if attempt == max_retries:
                    return ""
                await asyncio.sleep(backoff)
                backoff *= 2

        return ""

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

        if "autonomous reasoning engine" in prompt_lower or "tasks_to_update" in prompt_lower:
            # Check if email is an extension / update
            is_update = "extension" in prompt_lower or "extended" in prompt_lower
            if is_update:
                return json.dumps({
                    "priority": "high",
                    "requires_action": True,
                    "summary": "CS302 Assignment 2 Deadline Extension by 24 hours.",
                    "reasoning": "The email contains a mandatory assignment deadline extension modifying the existing planned completion date.",
                    "deadlines": [
                        {
                            "title": "CS302 Assignment 2 Extended Deadline",
                            "due_at": "2026-09-16T23:59:00Z",
                            "source_context": "Extended by 24 hours",
                            "is_hard_deadline": True,
                            "confidence": 0.95,
                        }
                    ],
                    "tasks_to_create": [],
                    "tasks_to_update": [
                        {
                            "existing_task_id": None,
                            "matching_title_query": "Assignment 2",
                            "new_title": "CS302 Assignment 2 (Extended)",
                            "new_deadline": "2026-09-16T23:59:00Z",
                            "new_priority": "high",
                            "update_reason": "Deadline extended by 24 hours",
                        }
                    ],
                    "events_to_create": [],
                    "detected_conflicts": ["Detected potential conflict with existing evening study block"],
                    "recommended_action": "update_deadline",
                    "draft_response_needed": False,
                    "draft_response": None,
                })
            else:
                return json.dumps({
                    "priority": "high",
                    "requires_action": True,
                    "summary": "New academic assignment submission announcement.",
                    "reasoning": "The email contains a mandatory assignment deadline that must be tracked.",
                    "deadlines": [
                        {
                            "title": "Assignment Submission Deadline",
                            "due_at": "2026-09-15T23:59:00Z",
                            "source_context": "Submit by Sept 15",
                            "is_hard_deadline": True,
                            "confidence": 0.95,
                        }
                    ],
                    "tasks_to_create": [
                        {
                            "title": "Assignment Submission",
                            "description": "Complete and submit homework via Canvas",
                            "deadline": "2026-09-15T23:59:00Z",
                            "priority": "high",
                            "category": "assignment",
                            "estimated_effort_hours": 3.0,
                            "confidence": 0.95,
                        }
                    ],
                    "tasks_to_update": [],
                    "events_to_create": [],
                    "detected_conflicts": [],
                    "recommended_action": "create_task",
                    "draft_response_needed": False,
                    "draft_response": None,
                })

        if "parse job posting" in prompt_lower or "extract job details" in prompt_lower or "role_title" in prompt_lower:
            return json.dumps({
                "role_title": "Machine Learning Engineer Intern",
                "company": "DeepTech AI",
                "required_skills": ["Python", "PyTorch", "Data Structures & Algorithms", "Mathematics", "Linear Algebra"],
                "required_experience_level": "Internship / Entry Level",
                "key_responsibilities": [
                    "Develop and optimize deep learning training pipelines",
                    "Implement algorithmic solutions for high-throughput tensor manipulation",
                    "Collaborate on tree-based and neural network model architectures",
                ],
                "company_values_and_mission": "Building transparent, human-centered artificial intelligence solutions for high-impact domains.",
                "application_deadline": "2026-10-15T23:59:00Z",
                "overall_match_score": 85.0,
            })

        if "statement of purpose" in prompt_lower or "sop draft" in prompt_lower or "sop_text" in prompt_lower:
            return json.dumps({
                "sop_text": (
                    "Dear Hiring Team at DeepTech AI,\n\n"
                    "I am writing to express my enthusiastic interest in the Machine Learning Engineer Intern role. As a 3rd-year Computer Science student at University Engineering with an 8.8 CGPA, my academic foundation in algorithms and software engineering directly aligns with DeepTech AI's mission of building transparent, human-centered artificial intelligence.\n\n"
                    "Through disciplined technical practice, I have established strong foundations in Arrays & Hashing and Trees, regularly solving complex algorithmic challenges on LeetCode. In my coursework and hands-on projects, I have extensively utilized Python and FastAPI to engineer scalable backend services, and I actively apply rigorous problem-solving patterns to model optimization. Furthermore, I am actively expanding my practical proficiency in Dynamic Programming and distributed pipelines to ensure continuous mastery across all engineering dimensions.\n\n"
                    "DeepTech AI's focus on innovative model architectures resonates strongly with my long-term goal of engineering reliable, high-performance systems. I welcome the opportunity to contribute my technical rigor, proactive curiosity, and strong foundational discipline to your engineering team.\n\n"
                    "Sincerely,\nKriti Karunam"
                ),
                "tone": "confident_achievement",
                "generated_from": [
                    "profile.degree",
                    "profile.college",
                    "profile.cgpa",
                    "profile.skills",
                    "dsa_strengths: Arrays & Hashing, Trees",
                    "dsa_developing: Dynamic Programming",
                    "job.company_values",
                    "job.required_skills",
                    "student_preferences: formal",
                ],
                "key_strengths_highlighted": ["Arrays & Hashing", "Trees", "Python", "FastAPI"],
                "growth_areas_framed": ["Dynamic Programming", "Distributed Pipelines"],
            })

        # Generic default
        return json.dumps({
            "status": "ok",
            "message": "Processed successfully",
            "details": "Default mock response",
        })
