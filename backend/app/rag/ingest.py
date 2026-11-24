import argparse
import hashlib
import re
import uuid
from pathlib import Path
from typing import List, Tuple

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.rag.vectorstore import get_vectorstore

SUPPORTED_EXTENSIONS = {".md", ".txt"}
CHUNK_SIZE = 700
CHUNK_OVERLAP = 100

header_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "title"), ("##", "section")],
    strip_headers=True,
)
size_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
)


def parse_markdown(raw: str, filename: str) -> Tuple[str, str, str]:
    title_match = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
    title = (
        title_match.group(1).strip()
        if title_match
        else Path(filename).stem.replace("_", " ").title()
    )

    category_match = re.search(r"^Category:\s*(.+)$", raw, re.MULTILINE)
    category = category_match.group(1).strip() if category_match else "General"

    body = re.sub(r"^Category:\s*.+$\n?", "", raw, flags=re.MULTILINE)
    return title, category, body


def build_chunks(
    doc_id: str, title: str, category: str, filename: str, body: str
) -> List[Document]:
    sections = header_splitter.split_text(body)
    pieces = size_splitter.split_documents(sections)

    chunks: List[Document] = []
    for piece in pieces:
        content = piece.page_content.strip()
        if not content:
            continue
        index = len(chunks)
        section = piece.metadata.get("section", "Overview")
        chunks.append(
            Document(
                page_content=f"{title} - {section}\n{content}",
                metadata={
                    "doc_id": doc_id,
                    "title": title,
                    "category": category,
                    "section": section,
                    "source_filename": filename,
                    "chunk_index": index,
                },
            )
        )
    return chunks


def delete_document(db: Session, vs, doc_id: str) -> None:
    existing_ids = vs.get(where={"doc_id": doc_id})["ids"]
    if existing_ids:
        vs.delete(ids=existing_ids)
    db.execute(
        text("DELETE FROM kb_documents WHERE id = CAST(:id AS uuid)"),
        {"id": doc_id},
    )
    db.commit()


def reset_everything(db: Session) -> None:
    get_vectorstore().delete_collection()
    db.execute(text("DELETE FROM kb_documents"))
    db.commit()


def run(reset: bool = False) -> dict:
    kb_path = Path(settings.kb_dir)
    if not kb_path.is_dir():
        raise RuntimeError(f"Knowledge base folder not found: {kb_path}")

    files = sorted(
        p for p in kb_path.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    summary = {"added": 0, "updated": 0, "skipped": 0, "chunks_added": 0}

    db = SessionLocal()
    try:
        if reset:
            reset_everything(db)
            print("Reset: cleared vector collection and kb_documents table")

        vs = get_vectorstore()

        for path in files:
            raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
            content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

            existing = db.execute(
                text(
                    "SELECT id::text AS id, content_hash FROM kb_documents "
                    "WHERE source_filename = :fn"
                ),
                {"fn": path.name},
            ).mappings().first()

            if existing and existing["content_hash"].strip() == content_hash:
                print(f"unchanged  {path.name}")
                summary["skipped"] += 1
                continue

            duplicate = db.execute(
                text(
                    "SELECT source_filename FROM kb_documents "
                    "WHERE content_hash = :h AND source_filename <> :fn"
                ),
                {"h": content_hash, "fn": path.name},
            ).first()
            if duplicate:
                print(f"duplicate  {path.name} (same content as {duplicate[0]})")
                summary["skipped"] += 1
                continue

            was_update = existing is not None
            if was_update:
                delete_document(db, vs, existing["id"])

            doc_id = str(uuid.uuid4())
            title, category, body = parse_markdown(raw, path.name)
            chunks = build_chunks(doc_id, title, category, path.name, body)
            if not chunks:
                print(f"empty      {path.name}")
                summary["skipped"] += 1
                continue

            chunk_ids = [f"{doc_id}:{c.metadata['chunk_index']}" for c in chunks]

            try:
                vs.add_documents(chunks, ids=chunk_ids)
                db.execute(
                    text(
                        """
                        INSERT INTO kb_documents
                            (id, title, category, source_filename, content_hash, chunk_count)
                        VALUES
                            (CAST(:id AS uuid), :title, :category, :fn, :hash, :count)
                        """
                    ),
                    {
                        "id": doc_id,
                        "title": title,
                        "category": category,
                        "fn": path.name,
                        "hash": content_hash,
                        "count": len(chunks),
                    },
                )
                db.commit()
            except Exception:
                db.rollback()
                leftovers = vs.get(where={"doc_id": doc_id})["ids"]
                if leftovers:
                    vs.delete(ids=leftovers)
                raise

            label = "updated  " if was_update else "added    "
            print(f"{label}  {path.name:<28} {len(chunks):>3} chunks  [{category}]")
            summary["updated" if was_update else "added"] += 1
            summary["chunks_added"] += len(chunks)
    finally:
        db.close()

    print(
        f"Done: {summary['added']} added, {summary['updated']} updated, "
        f"{summary['skipped']} skipped, {summary['chunks_added']} chunks embedded"
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest IT SOPs into ChromaDB")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe the vector collection and kb_documents table before ingesting",
    )
    args = parser.parse_args()
    run(reset=args.reset)