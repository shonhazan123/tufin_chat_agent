"""LLM usage extraction from LangChain-style messages."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from agent.usage import extract_token_usage, InvocationUsage, record_llm_message


def test_extract_token_usage_openai_style():
    msg = AIMessage(content="hi")
    msg.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    u = extract_token_usage(msg)
    assert u["input_tokens"] == 10
    assert u["output_tokens"] == 5
    assert u["total_tokens"] == 15


def test_invocation_usage_accumulates():
    u = InvocationUsage()
    m1 = AIMessage(content="a")
    m1.usage_metadata = {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}
    m2 = AIMessage(content="b")
    m2.usage_metadata = {"input_tokens": 4, "output_tokens": 5, "total_tokens": 9}
    u.add_call("planner", m1)
    u.add_call("responder", m2)
    assert u.total_input_tokens == 5
    assert u.total_output_tokens == 7
    assert len(u.llm_calls) == 2


def test_record_llm_message_noop_without_context():
    msg = MagicMock()
    msg.usage_metadata = {}
    record_llm_message("planner", msg)  # no crash


def test_estimated_input_tokens_stored_in_entry():
    u = InvocationUsage()
    msg = AIMessage(content="hi")
    msg.usage_metadata = {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60}
    u.add_call("planner", msg, estimated_input_tokens=48)
    assert u.llm_calls[0]["estimated_input_tokens"] == 48
    assert u.llm_calls[0]["usage"]["input_tokens"] == 50


def test_estimated_fallback_when_provider_returns_none():
    """When provider returns no input tokens, the estimate is used as fallback."""
    u = InvocationUsage()
    msg = AIMessage(content="hi")
    msg.usage_metadata = {}
    u.add_call("planner", msg, estimated_input_tokens=100)
    assert u.total_input_tokens == 100
    assert u.llm_calls[0]["usage"]["input_tokens"] == 100


def test_provider_takes_priority_over_estimate():
    """Provider input_tokens are used when available (not the estimate)."""
    u = InvocationUsage()
    msg = AIMessage(content="hi")
    msg.usage_metadata = {"input_tokens": 42, "output_tokens": 8, "total_tokens": 50}
    u.add_call("planner", msg, estimated_input_tokens=100)
    assert u.total_input_tokens == 42
    assert u.llm_calls[0]["usage"]["input_tokens"] == 42


def test_no_estimate_and_no_provider_gives_none():
    """When neither provider nor estimate is available, input stays None."""
    u = InvocationUsage()
    msg = AIMessage(content="hi")
    msg.usage_metadata = {}
    u.add_call("planner", msg)
    assert u.total_input_tokens == 0
    assert u.llm_calls[0]["usage"]["input_tokens"] is None
