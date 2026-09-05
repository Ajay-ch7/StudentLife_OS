from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.base_models import TimestampMixin


class TelegramAlertDelivery(TimestampMixin, Base):
    __tablename__ = "telegram_alert_deliveries"
    __table_args__ = (
        UniqueConstraint("chat_id", "content_hash", name="uq_telegram_alert_delivery"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    chat_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    alert_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)