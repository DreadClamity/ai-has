from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_google_genai.embeddings import GoogleGenerativeAIError

from app.api import chat
from app.core.rbac import get_current_user
from app.database import get_db
from app.main import app
from app.services.llm import LLMUnavailable


@pytest.mark.parametrize("path", ["/chat/message", "/chat/message/stream"])
@pytest.mark.parametrize(
    "failure,expected",
    [
        (GoogleGenerativeAIError("API key not valid. private-provider-detail"), "rejected its API key"),
        (GoogleGenerativeAIError("upstream timeout private-provider-detail"), "unavailable"),
        (LLMUnavailable("API_KEY_INVALID private-provider-detail"), "rejected its API key"),
    ],
)
def test_provider_errors_are_readable_by_browser(monkeypatch, path, failure, expected):
    db = MagicMock()
    db.execute.return_value.scalar_one.return_value = str(uuid4())
    db.execute.return_value.mappings.return_value.all.return_value = []
    monkeypatch.setattr(chat, "find_pending_tool_call", lambda *args: None)
    monkeypatch.setattr(chat, "add_message", lambda *args: str(uuid4()))
    monkeypatch.setattr(chat.chat_limiter, "allow", lambda *args: (True, 0))

    def fail(*args):
        raise failure

    monkeypatch.setattr(chat, "answer_question", fail)
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: db)
    monkeypatch.setitem(
        app.dependency_overrides, get_current_user,
        lambda: {"id": str(uuid4()), "role": "employee"},
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            path, json={"message": "How do I connect to the VPN?"},
            headers={"Origin": "http://localhost:3000"},
        )
    assert response.status_code == 503
    assert expected in response.json()["detail"]
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "private-provider-detail" not in response.text
