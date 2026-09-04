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

        # Build clean, structured Telegram HTML notification
        user_header = f"👤 <b>User:</b> @{html.escape(user_display)}\n" if user_display else ""

        if newly_solved:
            grouped_blocks = []
            for topic, probs in grouped_problems.items():
                prob_lines = [
                    f"  • {html.escape(p.get('title', 'Problem'))} (<i>{html.escape(p.get('difficulty', 'Medium'))}</i>)"
                    for p in probs
                ]
                grouped_blocks.append(f"<b>{html.escape(topic)}</b>\n" + "\n".join(prob_lines))

            newly_solved_section = "\n\n".join(grouped_blocks)

            telegram_msg = (
                "📈 <b>DSA Progress Update</b>\n\n"
                f"{user_header}"
                f"🔥 <b>Streak:</b> {streak} days\n"
                f"📊 <b>Total Solved:</b> {total}\n\n"
                f"<b>Newly Solved</b>\n\n"
                f"{newly_solved_section}\n\n"
                f"💡 <b>OpenClaw Recommendation:</b>\n"
                f"{html.escape(recommendation_text)}"
            )
        else:
            telegram_msg = (
                "📈 <b>DSA Progress Summary</b>\n\n"
                f"{user_header}"
                f"🔥 <b>Streak:</b> {streak} days\n"
                f"📊 <b>Total Solved:</b> {total}\n\n"
                f"💡 <b>OpenClaw Recommendation:</b>\n"
                f"{html.escape(recommendation_text)}"
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

