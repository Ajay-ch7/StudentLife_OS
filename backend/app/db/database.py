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
			existing = {column["name"] for column in inspect(connection).get_columns("student_profiles")}
			for column, column_type in _profile_columns.items():
				if column not in existing:
					connection.execute(text(f"ALTER TABLE student_profiles ADD COLUMN {column} {column_type}"))
			event_columns = {column["name"] for column in inspect(connection).get_columns("calendar_events")}
			if "task_id" not in event_columns:
				connection.execute(text("ALTER TABLE calendar_events ADD COLUMN task_id INTEGER"))
			approval_columns = {column["name"] for column in inspect(connection).get_columns("approval_requests")}
			for column, column_type in {
				"metadata_json": "TEXT",
				"expires_at": "DATETIME",
				"result_json": "TEXT",
			}.items():
				if column not in approval_columns:
					connection.execute(text(f"ALTER TABLE approval_requests ADD COLUMN {column} {column_type}"))


def get_db() -> Generator:
	db = SessionLocal()
	try:
		yield db
	finally:
		db.close()
