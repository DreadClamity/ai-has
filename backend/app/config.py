from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://aihas:change_me_aihas@localhost:5432/aihas"

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    cors_origins: str = "http://localhost:3000"

    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-flash-lite-latest"
    gemini_embedding_model: str = "gemini-embedding-001"

    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection: str = "it_kb_sops"
    kb_dir: str = "/knowledge_base"
    rag_min_vector: float = 0.72
    rag_strong_vector: float = 0.85
    rag_top_k: int = 4
    chat_history_messages: int = 6

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()