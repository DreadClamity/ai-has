from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.rbac import get_current_user, require_roles
from app.database import get_db
from app.rag.ingest import run as run_ingest
from app.rag.retriever import retrieve
from app.schemas.kb import ChunkHit, KBDocumentOut

router = APIRouter(prefix="/kb", tags=["Knowledge Base"])


@router.get("/documents", response_model=List[KBDocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("agent", "admin")),
):
    rows = db.execute(
        text(
            """
            SELECT id::text AS id, title, category, source_filename,
                   chunk_count, created_at
            FROM kb_documents
            ORDER BY title
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/reindex")
def reindex(
    reset: bool = False,
    _admin: dict = Depends(require_roles("admin")),
):
    try:
        return run_ingest(reset=reset)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/search", response_model=List[ChunkHit])
def search(
    q: str = Query(..., min_length=3, max_length=500),
    k: int = Query(4, ge=1, le=10),
    _user: dict = Depends(get_current_user),
):
    try:
        return retrieve(q, k)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))