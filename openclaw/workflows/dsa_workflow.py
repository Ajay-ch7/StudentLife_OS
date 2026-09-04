import logging
from typing import Any
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.telegram_adapter import TelegramAdapter
from app.services.dsa_service import DSAService
from app.services.gemini_service import GeminiService
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

        # Get existing DSA summary
        summary = DSAService.summary(db, user_id)
        weak_topics = summary.get("weak_topics", [])

        # Generate recommendation using Gemini or smart fallback
        recommendation_text = ""
        if newly_solved:
            latest = newly_solved[0]
            title = latest.get("title", "Problem")
            diff = latest.get("difficulty", "Medium")
            topic = latest.get("topic", "General")

            rec_prompt = (
                f"Student solved a new LeetCode problem: '{title}' (Difficulty: {diff}, Topic: {topic}). "
                f"Total solved so far: {total_solved or summary['total']}. Current streak: {summary['streak']} days. "
                f"Weak topics needing practice: {', '.join(weak_topics[:3]) if weak_topics else 'None'}. "
                "Provide a 2-sentence encouraging analysis and specific recommendation for their next DSA practice step."
            )
            try:
                recommendation_text = await self.gemini.client.generate_text(prompt=rec_prompt)
            except Exception as err:
                logger.warning("Gemini recommendation generation fallback due to: %s", err)
                next_topic = weak_topics[0] if weak_topics else "Dynamic Programming"
                recommendation_text = f"Great work solving '{title}'! To maintain momentum, try tackling a medium problem in '{next_topic}' next."

        # Build Telegram update message
        if newly_solved:
            problems_str = "\n".join(
                [f"• <b>{p.get('title')}</b> ({p.get('difficulty')}) — <i>{p.get('topic')}</i>" for p in newly_solved]
            )
            telegram_msg = (
                "🎯 <b>LeetCode Goal Update</b>\n\n"
                f"👤 <b>User:</b> @{username or 'student'}\n"
                f"🔥 <b>Streak:</b> {summary['streak']} days\n"
                f"📊 <b>Total Solved:</b> {total_solved or summary['total']}\n\n"
                f"✅ <b>Newly Solved:</b>\n{problems_str}\n\n"
                f"💡 <b>OpenClaw Recommendation:</b>\n{recommendation_text}"
            )
        else:
            telegram_msg = (
                "🎯 <b>DSA Practice Summary</b>\n\n"
                f"📊 <b>Total Solved:</b> {summary['total']}\n"
                f"🔥 <b>Streak:</b> {summary['streak']} days\n"
                f"💡 <b>Recommendation:</b> Keep up the consistent daily practice!"
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
