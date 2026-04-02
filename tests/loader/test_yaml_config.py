"""Tests for merged YAML config (env-driven LLM_PROVIDER)."""

import os

import pytest

from agent.yaml_config import load_config


@pytest.fixture(autouse=True)
def clear_load_config_cache():
    load_config.cache_clear()
    yield
    load_config.cache_clear()


def test_load_config_openai_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    cfg = load_config()
    assert cfg["provider"] == "openai"
    assert cfg["agents"]["planner"]["model"] == "gpt-5.1"
    assert cfg["agents"]["weather"]["model"] == "gpt-4o-mini"
    assert "tools" in cfg
    assert cfg["tools"]["calculator"]["enabled"] is True


def test_load_config_ollama(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    cfg = load_config()
    assert cfg["provider"] == "ollama"
    assert cfg["agents"]["planner"]["model"] == "mistral"
    assert cfg["agents"]["planner"]["num_ctx"] == 4096
    assert cfg["agents"]["responder"]["num_ctx"] == 4096
    assert "ollama" not in cfg["tools"]


def test_load_config_invalid_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        load_config()


def test_llm_provider_defaults_to_openai(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    # load_config() calls load_dotenv(); repo .env may set LLM_PROVIDER — skip so default stays code-driven.
    monkeypatch.setattr("agent.yaml_config.load_dotenv", lambda *_a, **_k: None)
    cfg = load_config()
    assert cfg["provider"] == "openai"
