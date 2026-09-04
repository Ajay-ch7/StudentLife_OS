from dataclasses import dataclass

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
    ) -> TelegramMessage:
        resolved_chat_id = chat_id or self.settings.telegram_chat_id
        if not resolved_chat_id:
            raise ValueError("A Telegram chat ID is required to send a message")

        if self.settings.telegram_mock_mode:
            return TelegramMessage(
                chat_id=resolved_chat_id,
                text=text,
                mocked=True,
            )

        if not self.settings.telegram_bot_token:
            raise ValueError("A Telegram bot token is required for live delivery")

        endpoint = (
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        )
        async with httpx.AsyncClient(timeout=self.settings.gemini_timeout_seconds) as client:
            response = await client.post(
                endpoint,
                data={"chat_id": resolved_chat_id, "text": text},
            )
            response.raise_for_status()

        return TelegramMessage(
            chat_id=resolved_chat_id,
            text=text,
            mocked=False,
        )
