import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import List, Optional

from app.config import settings
from app.rag.vectorstore import get_vectorstore

RRF_K = 60
VECTOR_POOL = 12

STOPWORDS = {
    "a", "about", "am", "an", "and", "are", "as", "at", "be", "been", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has", "have", "how",
    "i", "if", "in", "into", "is", "it", "its", "me", "my", "of", "on", "or", "our",
    "please", "should", "so", "that", "the", "their", "them", "then", "there",
    "these", "they", "this", "to", "was", "we", "were", "what", "when", "where",
    "which", "who", "why", "will", "with", "would", "you", "your", "need", "want",
    "help", "like", "just", "get", "don", "doesn", "didn", "isn",
}


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: Optional[str]
    title: Optional[str]
    category: Optional[str]
    section: Optional[str]
    source_filename: Optional[str]
    text: str
    vector_relevance: Optional[float]
    keyword_score: float
    rrf_score: float


@dataclass
class RetrievalResult:
    chunks: List[RetrievedChunk]
    top_vector: float
    keyword_hit: bool
    confident: bool


def _stem(token: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> List[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [_stem(t) for t in tokens if len(t) >= 2 and t not in STOPWORDS]


def bm25_scores(
    query_tokens: List[str],
    doc_tokens: List[List[str]],
    k1: float = 1.5,
    b: float = 0.75,
) -> List[float]:
    n_docs = len(doc_tokens)
    if n_docs == 0:
        return []

    avg_len = sum(len(d) for d in doc_tokens) / n_docs or 1.0
    doc_freq: Counter = Counter()
    for tokens in doc_tokens:
        for term in set(tokens):
            doc_freq[term] += 1

    unique_query = set(query_tokens)
    scores: List[float] = []
    for tokens in doc_tokens:
        term_freq = Counter(tokens)
        length = len(tokens)
        score = 0.0
        for term in unique_query:
            if term not in term_freq:
                continue
            df = doc_freq[term]
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            tf = term_freq[term]
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avg_len))
        scores.append(score)
    return scores


def is_confident(top_vector: float, keyword_hit: bool) -> bool:
    if top_vector >= settings.rag_strong_vector:
        return True
    return top_vector >= settings.rag_min_vector and keyword_hit


def hybrid_retrieve(query: str, k: Optional[int] = None) -> RetrievalResult:
    k = k or settings.rag_top_k
    vs = get_vectorstore()

    vector_relevance = {}
    vector_order: List[str] = []
    for doc, distance in vs.similarity_search_with_score(query, k=VECTOR_POOL):
        chunk_id = f"{doc.metadata.get('doc_id')}:{doc.metadata.get('chunk_index')}"
        vector_relevance[chunk_id] = round(1.0 - float(distance), 4)
        vector_order.append(chunk_id)

    stored = vs.get(include=["documents", "metadatas"])
    ids = stored["ids"]
    documents = stored["documents"]
    metadatas = stored["metadatas"]

    if not ids:
        return RetrievalResult(chunks=[], top_vector=0.0, keyword_hit=False, confident=False)

    query_tokens = tokenize(query)
    keyword_scores = dict(
        zip(ids, bm25_scores(query_tokens, [tokenize(d) for d in documents]))
    )
    keyword_order = [
        cid
        for cid, score in sorted(keyword_scores.items(), key=lambda x: x[1], reverse=True)
        if score > 0
    ]

    fused = defaultdict(float)
    for rank, cid in enumerate(vector_order, start=1):
        fused[cid] += 1.0 / (RRF_K + rank)
    for rank, cid in enumerate(keyword_order, start=1):
        fused[cid] += 1.0 / (RRF_K + rank)

    position = {cid: i for i, cid in enumerate(ids)}
    chunks: List[RetrievedChunk] = []
    for cid in sorted(fused, key=fused.get, reverse=True)[:k]:
        i = position.get(cid)
        if i is None:
            continue
        meta = metadatas[i] or {}
        chunks.append(
            RetrievedChunk(
                chunk_id=cid,
                doc_id=meta.get("doc_id"),
                title=meta.get("title"),
                category=meta.get("category"),
                section=meta.get("section"),
                source_filename=meta.get("source_filename"),
                text=documents[i],
                vector_relevance=vector_relevance.get(cid),
                keyword_score=round(keyword_scores.get(cid, 0.0), 4),
                rrf_score=round(fused[cid], 5),
            )
        )

    top_vector = max(vector_relevance.values()) if vector_relevance else 0.0
    keyword_hit = bool(keyword_order)
    return RetrievalResult(
        chunks=chunks,
        top_vector=top_vector,
        keyword_hit=keyword_hit,
        confident=is_confident(top_vector, keyword_hit),
    )