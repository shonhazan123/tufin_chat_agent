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
