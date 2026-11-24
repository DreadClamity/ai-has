import time

from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings


class LLMUnavailable(Exception):
    pass


def get_llm() -> ChatGoogleGenerativeAI:
    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to .env and run: "
            "docker compose up -d --force-recreate backend"
        )
    return ChatGoogleGenerativeAI(
        model=settings.gemini_chat_model,
        google_api_key=settings.gemini_api_key,
        transport="rest",
        max_retries=0,
    )


def message_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


def invoke_with_tools(messages, tool_declarations, attempts: int = 2, delay: float = 3.0):
    llm = get_llm().bind_tools(tool_declarations)
    last_error = None
    for attempt in range(attempts):
        try:
            return llm.invoke(messages)
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(delay)
    raise LLMUnavailable(str(last_error)) from last_error