from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import agent, briefing, calendar, inbox, profile, resources, tasks, tools
from app.core.config import ensure_data_directories
from app.core.exceptions import unhandled_exception_handler
from app.core.logging import configure_logging
from app.db.database import init_db

configure_logging()
ensure_data_directories()
init_db()

app = FastAPI(title="Student Life OS API", version="0.1.0")
app.add_exception_handler(Exception, unhandled_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(profile.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")
app.include_router(calendar.router, prefix="/api/v1")
app.include_router(inbox.router, prefix="/api/v1")
app.include_router(briefing.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")
app.include_router(resources.router, prefix="/api/v1")


@app.get("/api/v1/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "student-life-os-backend"}


@app.get("/api/v1/ready")
def ready_check() -> dict[str, str]:
    return {"status": "ready"}
