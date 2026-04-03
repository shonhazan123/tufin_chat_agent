"""Memory context bundling and token caps per role."""

from __future__ import annotations

from agent.memory_budget_formatter import (
    PLANNER_MEMORY_MAX_TOKENS,
    build_planner_context_block,
    build_responder_memory_block,
    estimate_tokens,
)


def test_estimate_tokens_nonempty():
    assert estimate_tokens("hello") >= 1


def test_build_planner_context_block_respects_cap():
    huge = "word " * 2000
    block = build_planner_context_block(
        recent_messages=huge,
        context_summary=huge,
        max_tokens=PLANNER_MEMORY_MAX_TOKENS,
    )
    assert estimate_tokens(block) <= PLANNER_MEMORY_MAX_TOKENS


def test_build_responder_memory_block_respects_cap():
    huge = "fact " * 2000
    block = build_responder_memory_block(
        user_key_facts=huge,
        context_summary=huge,
        max_tokens=80,
    )
    assert estimate_tokens(block) <= 80
