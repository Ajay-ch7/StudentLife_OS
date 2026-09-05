from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings


@dataclass(frozen=True)
class TelegramMessage:
    chat_id: str
    text: str
    mocked: bool


class TelegramAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send_message(
        self,
        text: str,
        chat_id: str | None = None,
        parse_mode: str | None = None,
    ) -> TelegramMessage:
        resolved_chat_id = chat_id or self.settings.telegram_chat_id

        if self.settings.telegram_mock_mode:
            return TelegramMessage(
                chat_id=resolved_chat_id or "mock_student_chat",
                text=text,
                mocked=True,
            )

        if not resolved_chat_id:
            raise ValueError("A Telegram chat ID is required to send a live message")


        if not self.settings.telegram_bot_token:
            raise ValueError("A Telegram bot token is required for live delivery")

        endpoint = (
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        )
        payload: dict[str, Any] = {"chat_id": resolved_chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode

        async with httpx.AsyncClient(timeout=self.settings.gemini_timeout_seconds) as client:
            response = await client.post(
                endpoint,
                json=payload,
            )
            # Fallback if telegram fails to parse custom entities/HTML
            if response.status_code == 400 and parse_mode and "can't parse entities" in response.text:
                payload.pop("parse_mode", None)
                response = await client.post(
                    endpoint,
                    json=payload,
                )
            response.raise_for_status()

        return TelegramMessage(
            chat_id=resolved_chat_id,
            text=text,
            mocked=False,
        )
