import html
import logging
from typing import Any
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.telegram_adapter import TelegramAdapter
from app.schemas.orchestration_schemas import OrchestratorEvent, OrchestratorEventType
from app.services.dsa_service import DSAService
from app.services.gemini_service import GeminiService
from app.services.orchestrator import multi_agent_orchestrator
from openclaw.workflows.base_workflow import BaseWorkflow

logger = logging.getLogger(__name__)


class DSARecommendationWorkflow(BaseWorkflow):
    """
    OpenClaw workflow to analyze new LeetCode accepted submissions against the student's current
    DSA goals and progress, generating actionable next recommendations and dispatching Telegram alerts.
    """

    def __init__(self, agent=None, telegram_adapter: TelegramAdapter | None = None) -> None:
        super().__init__(name="dsa_recommendation", agent=agent)
        self.settings = get_settings()
        self.telegram = telegram_adapter or TelegramAdapter(self.settings)
        self.gemini = GeminiService()

    async def run(self, user_id: int, db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        workflow_id = self.generate_workflow_id()
        self.log_workflow_start(db, user_id, workflow_id, "Reviewing DSA practice progress & LeetCode updates")

        data = payload or {}
        newly_solved = data.get("newly_solved", [])
        total_solved = data.get("total_solved")
        username = data.get("username")

        # Orchestrator intercept: cross-agent context on new LeetCode solve
        try:
            orch_event = OrchestratorEvent(
                event_type=OrchestratorEventType.NEW_LEETCODE_SOLVE,
                user_id=user_id,
                payload={"newly_solved": newly_solved, "username": username},
                workflow_id=f"orch-dsa-{workflow_id}",
            )
            await multi_agent_orchestrator.run(orch_event, db)
        except Exception as orch_exc:
            logger.warning("Orchestrator intercept failed in DSA workflow (fallback): %s", orch_exc)

        # Get existing DSA summary
        summary = DSAService.summary(db, user_id)
        weak_topics = summary.get("weak_topics", [])
        streak = summary.get("streak", 0)
        total = total_solved if total_solved is not None else summary.get("total", 0)
        user_display = username or summary.get("username", "student")

        # Group newly solved problems cleanly by topic/category
        grouped_problems: dict[str, list[dict[str, Any]]] = {}
        for item in newly_solved:
            topic = item.get("topic") or "General"
            grouped_problems.setdefault(topic, []).append(item)

        # Generate recommendation using Gemini or personalized smart fallback
        recommendation_text = ""
        if newly_solved:
            topic_summary_parts = []
            for topic, probs in grouped_problems.items():
                diffs = [p.get("difficulty", "Medium") for p in probs]
                topic_summary_parts.append(f"{topic} ({', '.join(diffs)})")
            solved_summary_str = "; ".join(topic_summary_parts)

            rec_prompt = (
                f"Student solved new LeetCode problem(s): {solved_summary_str}. "
                f"Total solved so far: {total}. Current streak: {streak} days. "
                f"Weak topics needing practice: {', '.join(weak_topics[:3]) if weak_topics else 'None'}. "
                "Provide a concise, personalized 1-2 sentence OpenClaw recommendation for their next DSA practice step based on these solved topics and difficulties. Avoid excessive emojis or fluff."
            )
            try:
                raw_rec = await self.gemini.client.generate_text(prompt=rec_prompt)
                recommendation_text = raw_rec.strip() if raw_rec else ""
            except Exception as err:
                logger.warning("Gemini recommendation generation fallback due to: %s", err)

            if not recommendation_text:
                solved_topics_list = list(grouped_problems.keys())
                topics_str = ", ".join(solved_topics_list[:2])
                next_topic = weak_topics[0] if weak_topics else "Dynamic Programming"
                recommendation_text = (
                    f"Great progress solving problems in {topics_str}. "
                    f"To keep building mastery, try tackling a Medium problem in {next_topic} next."
                )
        else:
            rec_prompt = (
                f"Student's current DSA stats — Total Solved: {total}, Streak: {streak} days. "
                f"Weak topics needing practice: {', '.join(weak_topics[:3]) if weak_topics else 'None'}. "
                "Provide a concise 1-sentence encouraging recommendation for their daily DSA practice. Avoid excessive emojis."
            )
            try:
                raw_rec = await self.gemini.client.generate_text(prompt=rec_prompt)
                recommendation_text = raw_rec.strip() if raw_rec else ""
            except Exception as err:
                logger.warning("Gemini recommendation generation fallback due to: %s", err)

            if not recommendation_text:
                next_topic = weak_topics[0] if weak_topics else "Arrays & Hashing"
                recommendation_text = f"Maintain your daily momentum with a Medium problem in {next_topic}."

        # Build clean, human-readable notification (no HTML tags, no emojis)
        clean_user = user_display.lstrip("@") if user_display else ""
        user_header = f"User: @{clean_user}\n" if clean_user else ""

        if newly_solved:
            easy_c = sum(1 for p in newly_solved if (p.get("difficulty") or "").strip().lower() == "easy")
            med_c = sum(1 for p in newly_solved if (p.get("difficulty") or "").strip().lower() in ("medium", "med"))
            hard_c = sum(1 for p in newly_solved if (p.get("difficulty") or "").strip().lower() == "hard")

            breakdown_parts = []
            if easy_c:
                breakdown_parts.append(f"{easy_c} Easy")
            if med_c:
                breakdown_parts.append(f"{med_c} Medium")
            if hard_c:
                breakdown_parts.append(f"{hard_c} Hard")
            breakdown_str = f" ({', '.join(breakdown_parts)})" if breakdown_parts else ""

            total_new = len(newly_solved)
            problem_word = "problem" if total_new == 1 else "problems"

            grouped_blocks = []
            for topic, probs in grouped_problems.items():
                prob_lines = [
                    f"  • {p.get('title', 'Problem')} ({p.get('difficulty', 'Medium')})"
                    for p in probs
                ]
                grouped_blocks.append(f"{topic} ({len(probs)}):\n" + "\n".join(prob_lines))

            newly_solved_section = "\n\n".join(grouped_blocks)

            telegram_msg = (
                "DSA Progress Update\n"
                "----------------------------------------\n"
                f"{user_header}"
                f"Streak: {streak} days | Total Solved: {total}\n"
                f"Newly Solved: {total_new} {problem_word}{breakdown_str}\n"
                "----------------------------------------\n\n"
                f"{newly_solved_section}\n\n"
                "----------------------------------------\n"
                "OpenClaw Recommendation:\n"
                f"{recommendation_text}"
            )

            # Safeguard against Telegram 4096 character limit
            if len(telegram_msg) > 4000:
                trimmed_blocks = []
                curr_len = len(telegram_msg) - len(newly_solved_section)
                for block in grouped_blocks:
                    if curr_len + len(block) < 3700:
                        trimmed_blocks.append(block)
                        curr_len += len(block)
                    else:
                        trimmed_blocks.append("... and additional problems recorded")
                        break
                newly_solved_section = "\n\n".join(trimmed_blocks)
                telegram_msg = (
                    "DSA Progress Update\n"
                    "----------------------------------------\n"
                    f"{user_header}"
                    f"Streak: {streak} days | Total Solved: {total}\n"
                    f"Newly Solved: {total_new} {problem_word}{breakdown_str}\n"
                    "----------------------------------------\n\n"
                    f"{newly_solved_section}\n\n"
                    "----------------------------------------\n"
                    "OpenClaw Recommendation:\n"
                    f"{recommendation_text}"
                )
        else:
            telegram_msg = (
                "DSA Progress Summary\n"
                "----------------------------------------\n"
                f"{user_header}"
                f"Streak: {streak} days | Total Solved: {total}\n"
                "----------------------------------------\n\n"
                "OpenClaw Recommendation:\n"
                f"{recommendation_text}"
            )

        # Dispatch Telegram message if chat ID is configured
        telegram_sent = False
        target_chat_id = self.settings.telegram_chat_id
        try:
            msg_res = await self.telegram.send_message(text=telegram_msg, chat_id=target_chat_id)
            telegram_sent = True
            logger.info("Dispatched DSA LeetCode update to Telegram (mocked: %s)", msg_res.mocked)
        except Exception as err:
            logger.warning("Failed to dispatch DSA update to Telegram: %s", err)

        self.log_workflow_complete(
            db,
            user_id,
            workflow_id,
            "DSA progress reviewed & recommendation generated",
            {"newly_solved_count": len(newly_solved), "telegram_sent": telegram_sent},
        )

        return {
            "workflow_id": workflow_id,
            "status": "completed",
            "recommendation": recommendation_text,
            "telegram_sent": telegram_sent,
            "summary": summary,
        }

