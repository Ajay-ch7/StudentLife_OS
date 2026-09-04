import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR))

from app.db.database import SessionLocal, init_db
from app.models.email_message import EmailMessage
from app.integrations.gmail_adapter import GmailAdapter

init_db()
db = SessionLocal()
adapter = GmailAdapter()
msgs = adapter.list_recent_messages(query="", max_results=20)
saved = 0
for m in msgs:
    gmail_id = m.get("id")
    if not gmail_id:
        continue
    existing = db.query(EmailMessage).filter(EmailMessage.gmail_id == gmail_id).first()
    if not existing:
        email_record = EmailMessage(
            user_id=1,
            gmail_id=gmail_id,
            thread_id=m.get("thread_id"),
            sender=m.get("from", "Unknown")[:250],
            subject=m.get("subject", "No Subject")[:500],
            snippet=m.get("snippet", "")[:1000],
            body=m.get("body", "")[:5000],
            date_str=m.get("date", ""),
            category="career" if any(k in (m.get("from","")+m.get("subject","")).lower() for k in ["career", "intern", "job", "unstop"]) else "general",
        )
        db.add(email_record)
        saved += 1
db.commit()
print(f"Saved {saved} new emails into SQLite database. Total emails in DB: {db.query(EmailMessage).count()}")
db.close()
