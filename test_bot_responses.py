import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR))

from app.db.database import SessionLocal
from app.services.telegram_bot_listener import TelegramBotListener

async def test_bot() -> None:
    db = SessionLocal()
    listener = TelegramBotListener()

    print("--- 1. Testing /calendar command ---")
    cal_res = await listener.handle_command("/calendar", user_id=1, db=db)
    print(cal_res)

    print("\n--- 2. Testing /tasks command ---")
    tasks_res = await listener.handle_command("/tasks", user_id=1, db=db)
    print(tasks_res)

    print("\n--- 3. Testing /drafts command ---")
    drafts_res = await listener.handle_command("/drafts", user_id=1, db=db)
    print(drafts_res)

    print("\n--- 4. Testing /approve command ---")
    approve_res = await listener.handle_command("/approve 1", user_id=1, db=db)
    print(approve_res)

    db.close()

if __name__ == "__main__":
    asyncio.run(test_bot())
