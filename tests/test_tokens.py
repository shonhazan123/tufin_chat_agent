"""Tests for agent.token_usage_tracker — tiktoken counting + 3-way usage tracking."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.token_usage_tracker import (
    _count_messages_split,
    _extract_provider_usage,
    count_tokens,
    get_usage,
    record_llm_call,
    reset_usage,
)


# ---------------------------------------------------------------------------
# count_tokens (plain text)
# ---------------------------------------------------------------------------

def test_count_tokens_empty():
    assert count_tokens("") == 0


def test_count_tokens_basic():
    tokens = count_tokens("Hello, world!")
    assert isinstance(tokens, int)
    assert tokens > 0


def test_count_tokens_different_models():
    text = "The quick brown fox jumps over the lazy dog."
    t1 = count_tokens(text, model="gpt-4o-mini")
    t2 = count_tokens(text, model="gpt-4")
    assert t1 > 0 and t2 > 0


def test_count_tokens_unknown_model():
    tokens = count_tokens("Test text", model="some-unknown-model-xyz")
    assert tokens > 0


# ---------------------------------------------------------------------------
# _count_messages_split (cached vs input)
# ---------------------------------------------------------------------------

def test_split_system_vs_human():
    messages = [
        SystemMessage(content="You are a helpful assistant."),
        HumanMessage(content="What is 2+2?"),
    ]
    cached, inp = _count_messages_split(messages, "gpt-4o-mini")
    assert cached > 0
    assert inp > 0


def test_split_no_system_message():
    messages = [HumanMessage(content="Hello")]
    cached, inp = _count_messages_split(messages, "gpt-4o-mini")
    assert cached == 0
    assert inp > 0


def test_split_dict_messages():
    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "User input"},
    ]
    cached, inp = _count_messages_split(messages, "gpt-4o-mini")
    assert cached > 0
    assert inp > 0


# ---------------------------------------------------------------------------
# _extract_provider_usage
# ---------------------------------------------------------------------------

def test_extract_openai_style():
    msg = AIMessage(content="hi")
    msg.usage_metadata = {"input_tokens": 10, "output_tokens": 5}
    u = _extract_provider_usage(msg)
    assert u["input_tokens"] == 10
    assert u["output_tokens"] == 5


def test_extract_empty_metadata():
    msg = AIMessage(content="hi")
    msg.usage_metadata = {}
    u = _extract_provider_usage(msg)
    assert u["input_tokens"] is None
    assert u["output_tokens"] is None


# ---------------------------------------------------------------------------
# record_llm_call + InvocationUsage (3-way split)
# ---------------------------------------------------------------------------

def test_record_produces_3way_split():
    reset_usage()
    messages = [
        SystemMessage(content="You are a math expert."),
        HumanMessage(content="What is 2+2?"),
    ]
    msg = AIMessage(content="4")
    msg.usage_metadata = {"input_tokens": 25, "output_tokens": 3}
    record_llm_call("planner", msg, messages=messages, model="gpt-4o-mini")
    u = get_usage()
    assert u is not None
    assert u.total_cached_tokens > 0
    assert u.total_input_tokens > 0
    assert u.total_output_tokens == 3
    entry = u.llm_calls[0]
    assert entry["usage"]["cached_tokens"] > 0
    assert entry["usage"]["input_tokens"] > 0
    assert entry["usage"]["output_tokens"] == 3


def test_accumulation_across_calls():
    reset_usage()
    m1 = AIMessage(content="a")
    m1.usage_metadata = {"input_tokens": 20, "output_tokens": 5}
    m2 = AIMessage(content="b")
    m2.usage_metadata = {"input_tokens": 30, "output_tokens": 10}

    msgs1 = [SystemMessage(content="sys"), HumanMessage(content="q1")]
    msgs2 = [SystemMessage(content="sys"), HumanMessage(content="q2")]

    record_llm_call("planner", m1, messages=msgs1, model="gpt-4o-mini")
    record_llm_call("responder", m2, messages=msgs2, model="gpt-4o-mini")

    u = get_usage()
    assert u is not None
    assert len(u.llm_calls) == 2
    assert u.total_output_tokens == 15
    assert u.total_cached_tokens > 0
    assert u.total_input_tokens > 0


def test_fallback_when_provider_returns_none():
    reset_usage()
    messages = [
        SystemMessage(content="System prompt here."),
        HumanMessage(content="User query here."),
    ]
    msg = AIMessage(content="response")
    msg.usage_metadata = {}
    record_llm_call("planner", msg, messages=messages, model="gpt-4o-mini")
    u = get_usage()
    assert u is not None
    assert u.total_cached_tokens > 0
    assert u.total_input_tokens > 0


def test_noop_without_active_usage():
    msg = MagicMock()
    msg.usage_metadata = {}
    record_llm_call("planner", msg)


def test_no_messages_kwarg():
    """When messages is not passed, only provider output tokens are captured."""
    reset_usage()
    msg = AIMessage(content="hi")
    msg.usage_metadata = {"input_tokens": 50, "output_tokens": 10}
    record_llm_call("planner", msg, model="gpt-4o-mini")
    u = get_usage()
    assert u is not None
    assert u.total_input_tokens == 50
    assert u.total_cached_tokens == 0
    assert u.total_output_tokens == 10
