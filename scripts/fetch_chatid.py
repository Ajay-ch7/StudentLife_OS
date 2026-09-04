"""
Fetch real Telegram chat_id from bot updates (clears offset to get fresh messages).
"""
import asyncio
import sys
import httpx

from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "backend"))
from app.core.config import get_settings

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOKEN = get_settings().telegram_bot_token
BASE  = f"https://api.telegram.org/bot{TOKEN}"


async def main() -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        # Try getUpdates with no offset (get everything buffered)
        for attempt, params in enumerate([
            {"limit": 100},
            {"limit": 100, "offset": -100},
            {"limit": 100, "allowed_updates": ["message", "channel_post", "callback_query"]},
        ], 1):
            print(f"\n--- Attempt {attempt} ---")
            r = await client.get(f"{BASE}/getUpdates", params=params)
            data = r.json()
            print(f"Status: {r.status_code} | Updates count: {len(data.get('result', []))}")
            for upd in data.get("result", []):
                for key in ("message", "channel_post", "edited_message"):
                    msg = upd.get(key)
                    if msg:
                        chat = msg.get("chat", {})
                        frm  = msg.get("from", {})
                        print(f"  Update ID  : {upd.get('update_id')}")
                        print(f"  Chat ID    : {chat.get('id')}")
                        print(f"  Chat type  : {chat.get('type')}")
                        print(f"  Username   : @{frm.get('username') or chat.get('username')}")
                        print(f"  Text       : {msg.get('text', '')[:60]}")
                        print()


if __name__ == "__main__":
    asyncio.run(main())
