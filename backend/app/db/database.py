from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
Base = declarative_base()


def init_db() -> None:
	from app import models  # noqa: F401

	Base.metadata.create_all(bind=engine)
	if settings.database_url.startswith("sqlite"):
		_profile_columns = {
			"skills": "VARCHAR(1000)",
			"preferred_locations": "VARCHAR(500)",
			"available_study_hours": "FLOAT",
			"preferred_study_times": "VARCHAR(500)",
			"notification_preferences": "VARCHAR(1000)",
		}
		with engine.begin() as connection:
			# Migrate users table
			user_columns = {column["name"] for column in inspect(connection).get_columns("users")}
			if "telegram_name" not in user_columns:
				connection.execute(text("ALTER TABLE users ADD COLUMN telegram_name VARCHAR(255)"))

			# Migrate student_profiles table
			existing = {column["name"] for column in inspect(connection).get_columns("student_profiles")}
			for column, column_type in _profile_columns.items():
				if column not in existing:
					connection.execute(text(f"ALTER TABLE student_profiles ADD COLUMN {column} {column_type}"))
			event_columns = {column["name"] for column in inspect(connection).get_columns("calendar_events")}
			for column, column_type in {
				"task_id": "INTEGER",
				"google_event_id": "VARCHAR(255)",
				"creation_notified": "BOOLEAN DEFAULT 0",
				"reminded_day_before": "BOOLEAN DEFAULT 0",
			}.items():
				if column not in event_columns:
					connection.execute(text(f"ALTER TABLE calendar_events ADD COLUMN {column} {column_type}"))
			approval_columns = {column["name"] for column in inspect(connection).get_columns("approval_requests")}
			for column, column_type in {
				"metadata_json": "TEXT",
				"expires_at": "DATETIME",
				"result_json": "TEXT",
			}.items():
				if column not in approval_columns:
					connection.execute(text(f"ALTER TABLE approval_requests ADD COLUMN {column} {column_type}"))

			# Migrate email_messages table
			email_columns = {column["name"] for column in inspect(connection).get_columns("email_messages")}
			for column, column_type in {
				"processing_status": "VARCHAR(50) DEFAULT 'new'",
				"priority": "VARCHAR(50)",
				"requires_action": "BOOLEAN DEFAULT 0",
				"action_type": "VARCHAR(100)",
				"reasoning": "TEXT",
				"processed_at": "DATETIME",
				"error_message": "TEXT",
			}.items():
				if column not in email_columns:
					connection.execute(text(f"ALTER TABLE email_messages ADD COLUMN {column} {column_type}"))


def get_db() -> Generator:
	db = SessionLocal()
	try:
		yield db
	finally:
		db.close()
