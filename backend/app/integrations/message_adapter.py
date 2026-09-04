from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class ChatMessage:
    channel_or_sender: str
    content: str
    sent_at: datetime
    platform: str


class MessageAdapter:
    """Parses chat messages from Discord, Slack, Telegram, or WhatsApp study groups."""

    @classmethod
    def parse_message(
        cls,
        content: str,
        channel_or_sender: str = "Class Group",
        platform: str = "Discord",
        sent_at: datetime | None = None,
    ) -> ChatMessage:
        return ChatMessage(
            channel_or_sender=channel_or_sender,
            content=content.strip(),
            sent_at=sent_at or datetime.now(timezone.utc),
            platform=platform,
        )
