"""
Live-poll Telegram for 30s. Send a message to the bot NOW while this runs.
On success: sends a live test reply back AND updates .env with the real chat_id.
"""
import asyncio
import re
import sys
import httpx
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "backend"))
from app.core.config import get_settings

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOKEN = get_settings().telegram_bot_token
BASE  = f"https://api.telegram.org/bot{TOKEN}"
ENV   = ROOT_DIR / ".env"


async def main() -> None:
    print("Waiting 30s for a message — send any text to @StudentLife_OS_bot NOW...")
    async with httpx.AsyncClient(timeout=35) as c:
        r = await c.get(f"{BASE}/getUpdates", params={"timeout": 30, "limit": 5})

    updates = r.json().get("result", [])
    if not updates:
        print("No message received in the 30-second window.")
        return

    for upd in updates:
        msg     = upd.get("message") or upd.get("channel_post") or {}
        chat    = msg.get("chat", {})
        sender  = msg.get("from", {})
        chat_id = chat.get("id")
        if not chat_id:
            continue

        username = sender.get("username") or chat.get("username") or "N/A"
        text     = msg.get("text", "")

        print(f"\nMessage received!")
        print(f"  chat_id  : {chat_id}")
        print(f"  username : @{username}")
        print(f"  text     : {text[:80]}")

        # Send a live test message back
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.post(f"{BASE}/sendMessage", data={
                "chat_id": str(chat_id),
                "text": (
                    "StudentLife OS is now LIVE!\n\n"
                    "Your Telegram bot, Gemini AI and OpenClaw local agent are all connected.\n"
                    "Start the app and trigger a Morning Briefing to try it out."
                ),
            })
        if resp.json().get("ok"):
            print(f"  [OK] Live test message sent back to {chat_id}!")
        else:
            print(f"  [FAIL] Send error: {resp.json()}")

        # Patch .env with real numeric chat_id
        env_text = ENV.read_text(encoding="utf-8")
        patched  = re.sub(
            r"^TELEGRAM_CHAT_ID=.*$",
            f"TELEGRAM_CHAT_ID={chat_id}",
            env_text,
            flags=re.MULTILINE,
        )
        ENV.write_text(patched, encoding="utf-8")
        print(f"  [OK] .env updated: TELEGRAM_CHAT_ID={chat_id}")
        break


if __name__ == "__main__":
    asyncio.run(main())
