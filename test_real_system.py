import sys
import asyncio
import json
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR))

print("==================================================")
print(" 1. TESTING BACKEND REST ENDPOINTS")
print("==================================================")
endpoints = [
    "/api/v1/health",
    "/api/v1/profile",
    "/api/v1/tasks",
    "/api/v1/opportunities",
    "/api/v1/calendar",
    "/api/v1/dsa",
]
for ep in endpoints:
    try:
        req = urllib.request.urlopen(f"http://localhost:8000{ep}")
        data = json.loads(req.read().decode())
        if ep == "/api/v1/profile":
            user_data = data.get("user", {})
            print(f" [OK] {ep} -> User: {user_data.get('full_name')} ({user_data.get('email')}) [@{user_data.get('telegram_name')}]")
        elif ep == "/api/v1/tasks":
            print(f" [OK] {ep} -> {len(data)} Tasks loaded from Gmail")
        elif ep == "/api/v1/opportunities":
            print(f" [OK] {ep} -> {len(data)} Opportunities detected from Gmail")
        else:
            print(f" [OK] {ep} -> Status 200 OK")
    except Exception as e:
        print(f" [FAIL] {ep}: {e}")

print("\n==================================================")
print(" 2. TESTING OPENCLAW AGENT & TELEGRAM BOT REASONING")
print("==================================================")
from app.db.database import SessionLocal
from app.services.telegram_bot_listener import TelegramBotListener

async def test_bot():
    db = SessionLocal()
    listener = TelegramBotListener()
    queries = [
        "Check my emails for any new updates or notices",
        "What tasks do I have scheduled?",
        "Sync my calendar with google",
    ]
    for q in queries:
        print(f"\n>> User: \"{q}\"")
        ans = await listener.handle_natural_language(q, user_id=1, db=db)
        safe_ans = ans.encode("ascii", errors="replace").decode("ascii")
        print(f">> OpenClaw Bot Reply:\n{safe_ans}")
    db.close()

if __name__ == "__main__":
    asyncio.run(test_bot())
