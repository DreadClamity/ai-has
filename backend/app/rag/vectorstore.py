import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.config import settings


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to .env and run: "
            "docker compose up -d --force-recreate backend"
        )
    return GoogleGenerativeAIEmbeddings(
        model=f"models/{settings.gemini_embedding_model}",
        google_api_key=settings.gemini_api_key,
    )


def get_chroma_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_vectorstore() -> Chroma:
    return Chroma(
        client=get_chroma_client(),
        collection_name=settings.chroma_collection,
        embedding_function=get_embeddings(),
        collection_metadata={"hnsw:space": "cosine"},
    )