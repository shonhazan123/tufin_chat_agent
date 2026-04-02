"""Tests for agent.token_counter — tiktoken-based pre-call counting."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from agent.token_counter import count_chat_tokens, count_text_tokens


def test_count_text_tokens_empty():
    assert count_text_tokens("") == 0


def test_count_text_tokens_basic():
    tokens = count_text_tokens("Hello, world!")
    assert isinstance(tokens, int)
    assert tokens > 0


def test_count_text_tokens_different_models():
    text = "The quick brown fox jumps over the lazy dog."
    t1 = count_text_tokens(text, model="gpt-4o-mini")
    t2 = count_text_tokens(text, model="gpt-4")
    assert t1 > 0 and t2 > 0


def test_count_chat_tokens_langchain_messages():
    messages = [
        SystemMessage(content="You are a helpful assistant."),
        HumanMessage(content="What is the capital of France?"),
    ]
    tokens = count_chat_tokens(messages, model="gpt-4o-mini")
    assert tokens > 0
    assert tokens > count_text_tokens("You are a helpful assistant.")


def test_count_chat_tokens_dict_messages():
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is 2+2?"},
    ]
    tokens = count_chat_tokens(messages, model="gpt-4o-mini")
    assert tokens > 0


def test_count_chat_tokens_includes_overhead():
    """Chat format adds per-message overhead + assistant priming tokens."""
    text = "Hello"
    raw = count_text_tokens(text, model="gpt-4o-mini")
    chat = count_chat_tokens([HumanMessage(content=text)], model="gpt-4o-mini")
    assert chat > raw


def test_unknown_model_falls_back():
    tokens = count_text_tokens("Test text", model="some-unknown-model-xyz")
    assert tokens > 0
