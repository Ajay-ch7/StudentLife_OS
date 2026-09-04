import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR))

from app.db.database import SessionLocal
from app.services.telegram_bot_listener import TelegramBotListener

async def test():
    db = SessionLocal()
    listener = TelegramBotListener()
    queries = [
        "Find me job opportunities",
        "What internships are available?",
        "Do I have any tasks?"
    ]
    for q in queries:
        print(f"\n>> User: \"{q}\"")
        ans = await listener.handle_natural_language(q, user_id=1, db=db)
        print(f">> Bot Reply:\n{ans.encode('ascii', errors='replace').decode('ascii')}")
    db.close()

if __name__ == "__main__":
    asyncio.run(test())
