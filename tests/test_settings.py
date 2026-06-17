# tests/test_settings.py
from compresearch.settings import get_secret


def test_get_secret_reads_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    assert get_secret("ANTHROPIC_API_KEY") == "sk-test-123"


def test_get_secret_missing_returns_none(monkeypatch):
    monkeypatch.delenv("DEFINITELY_MISSING_KEY", raising=False)
    assert get_secret("DEFINITELY_MISSING_KEY") is None
