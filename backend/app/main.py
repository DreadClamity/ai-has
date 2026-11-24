from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.auth import router as auth_router
from app.api.kb import router as kb_router
from app.api.chat import router as chat_router
from app.api.tools import router as tools_router
from app.api.webhooks import router as webhooks_router
from app.api.agent import employee_router, router as agent_router
from app.api.metrics import router as metrics_router
from app.api.stream import router as stream_router
from app.config import settings
from app.database import get_db

app = FastAPI(
    title="AI-HAS API",
    version="0.3.0",
    description="AI-Powered Enterprise Helpdesk & Workflow Automation System",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(kb_router)
app.include_router(chat_router)
app.include_router(tools_router)
app.include_router(webhooks_router)
app.include_router(agent_router)
app.include_router(employee_router)
app.include_router(metrics_router)
app.include_router(stream_router)


@app.get("/health", tags=["System"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "down"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
        "version": app.version,
    }