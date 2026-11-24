import sys
from typing import List

from app.rag.vectorstore import get_vectorstore


def retrieve(query: str, k: int = 4) -> List[dict]:
    vs = get_vectorstore()
    results = vs.similarity_search_with_score(query, k=k)

    hits: List[dict] = []
    for doc, distance in results:
        meta = doc.metadata
        hits.append(
            {
                "chunk_id": f"{meta.get('doc_id')}:{meta.get('chunk_index')}",
                "doc_id": meta.get("doc_id"),
                "title": meta.get("title"),
                "category": meta.get("category"),
                "section": meta.get("section"),
                "source_filename": meta.get("source_filename"),
                "relevance": round(1.0 - float(distance), 4),
                "text": doc.page_content,
            }
        )
    return hits


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print('Usage: python -m app.rag.retriever "your question here"')
        sys.exit(1)

    for rank, hit in enumerate(retrieve(question), start=1):
        print(
            f"#{rank}  relevance={hit['relevance']:.3f}  "
            f"{hit['title']} > {hit['section']}  ({hit['source_filename']})"
        )
        print(f"    {hit['text'][:160].replace(chr(10), ' ')}...")