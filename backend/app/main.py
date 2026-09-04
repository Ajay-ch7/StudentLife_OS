import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import academic, agent, approvals, briefing, calendar, dsa, inbox, opportunities, orchestrator, profile, resources, tasks, tools
from app.core.config import ensure_data_directories, get_settings
from app.core.exceptions import unhandled_exception_handler
from app.core.logging import configure_logging
from app.db.database import init_db
from app.services.leetcode_watcher_service import leetcode_watcher_service
from app.services.realtime_sync_service import realtime_sync_service
from app.services.telegram_bot_listener import telegram_bot_listener

configure_logging()
ensure_data_directories()
init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    polling_task = None
    sync_task = None
    leetcode_task = None
    if settings.telegram_polling_enabled and not settings.telegram_mock_mode and settings.telegram_bot_token:
        polling_task = asyncio.create_task(telegram_bot_listener.start_polling())
    
    # Start continuous background Gmail & Calendar real-time sync
    sync_task = asyncio.create_task(realtime_sync_service.start_periodic_sync())

    # Start autonomous LeetCode polling watcher
    leetcode_task = asyncio.create_task(leetcode_watcher_service.start_periodic_sync())

    yield

    if polling_task:
        telegram_bot_listener.stop()
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass

    if sync_task:
        realtime_sync_service.stop()
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass

    if leetcode_task:
        leetcode_watcher_service.stop()
        leetcode_task.cancel()
        try:
            await leetcode_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Student Life OS API", version="0.1.0", lifespan=lifespan)
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
app.include_router(approvals.router, prefix="/api/v1")
app.include_router(academic.router, prefix="/api/v1")
app.include_router(opportunities.router, prefix="/api/v1")
app.include_router(dsa.router, prefix="/api/v1")
app.include_router(resources.router, prefix="/api/v1")
app.include_router(orchestrator.router, prefix="/api/v1")


@app.get("/api/v1/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "student-life-os-backend"}


@app.get("/api/v1/ready")
def ready_check() -> dict[str, str]:
    return {"status": "ready"}
