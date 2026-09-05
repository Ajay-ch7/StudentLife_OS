import asyncio
import sys
import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "backend"))
from app.core.config import get_settings

settings = get_settings()
TOKEN = settings.telegram_bot_token
CHAT_ID = settings.telegram_chat_id

MSG = (
    "StudentLife OS is now LIVE!\n\n"
    "Your setup is complete:\n"
    "- Gemini AI (gemini-3.1-flash-lite) connected\n"
    "- Telegram bot active\n"
    "- OpenClaw local agent ready\n\n"
    "Run start.py to launch the full app.\n"
    "Morning Briefings will be delivered right here!"
)


async def main() -> None:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": MSG},
        )
    result = r.json()
    if result.get("ok"):
        msg_id = result["result"]["message_id"]
        print(f"[OK] Message delivered to chat {CHAT_ID}! (message_id={msg_id})")
    else:
        print(f"[FAIL] {result.get('description')}")
        print(f"       Full response: {result}")


if __name__ == "__main__":
    asyncio.run(main())
