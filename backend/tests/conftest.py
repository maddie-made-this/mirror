import os
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# Satisfy required Settings fields BEFORE anything imports `config.loader`
# (which reads settings at import time for env overrides).
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NEO4J_PASSWORD", "test-neo4j-password")


@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
def conversation_id():
    return uuid4()


@pytest.fixture
def message_id():
    return uuid4()


@pytest.fixture
def mock_llm(monkeypatch):
    """
    Patch the chat() function everywhere it has been imported by name, so any
    service that calls it hits the controllable AsyncMock instead of the network.
    """
    mock = AsyncMock()
    monkeypatch.setattr("llm.client.chat", mock, raising=False)
    monkeypatch.setattr("services.extraction.chat", mock, raising=False)
    monkeypatch.setattr("services.response_gen.chat", mock, raising=False)
    monkeypatch.setattr("services.safety.chat", mock, raising=False)
    return mock


@pytest.fixture
def mock_qdrant(monkeypatch):
    client = MagicMock()
    client.query_points = AsyncMock(return_value=MagicMock(points=[]))
    client.upsert = AsyncMock()
    monkeypatch.setattr("db.qdrant.get_client", lambda: client, raising=False)
    return client


@pytest.fixture
def no_reflection(monkeypatch):
    """Disable the Pass 2 reflection extraction so a test exercises a single pass."""
    from config.loader import APP_CONFIG
    monkeypatch.setattr(APP_CONFIG, "reflection_system_prompt", "")
