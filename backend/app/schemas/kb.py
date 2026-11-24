from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class KBDocumentOut(BaseModel):
    id: str
    title: str
    category: Optional[str] = None
    source_filename: str
    chunk_count: int
    created_at: datetime


class ChunkHit(BaseModel):
    chunk_id: str
    doc_id: Optional[str] = None
    title: Optional[str] = None
    category: Optional[str] = None
    section: Optional[str] = None
    source_filename: Optional[str] = None
    relevance: float
    text: str