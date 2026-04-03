"""Conversation context manager — process-lifetime singleton.

Maintains a rolling window of recent messages, an LLM-generated summary, and durable
``user_key_facts``. Not part of AgentState — this is global, not per-request.
"""

from __future__ import annotations

import json
import logging
from collections import deque

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agent.llm_system_prompts import SUMMARIZER_SYSTEM

logger = logging.getLogger(__name__)

USER_MSG_PREFIX = "[user msg]\n"
ASSISTANT_MSG_PREFIX = "[assistant msg]\n"


class ConversationContext:
    """Rolling conversation context with summarization."""

    def __init__(self) -> None:
        self._turns: deque[tuple[str, str]] = deque(maxlen=5)
        self._pending_user: str | None = None
        self.summary: str = ""
        self.user_key_facts: str = ""
        self.last_tools_used: list[str] = []

    def set_last_tools(self, tools: list[str]) -> None:
        """Record which tools were invoked in the most recent turn."""
        self.last_tools_used = list(tools)

    def add_user(self, text: str) -> None:
        """Record a user message. Stored as pending until the assistant responds."""
        self._pending_user = text

    def add_assistant(self, text: str) -> None:
        """Pair the pending user message with this assistant reply to form a complete turn."""
        user_text = self._pending_user or ""
        self._pending_user = None
        self._turns.append((user_text, text))

    def window(self) -> list[BaseMessage]:
        """Return chronological message list (user/assistant pairs) as LangChain messages."""
        msgs: list[BaseMessage] = []
        for user_text, ai_text in self._turns:
            msgs.append(HumanMessage(content=f"{USER_MSG_PREFIX}{user_text}"))
            msgs.append(HumanMessage(content=f"{ASSISTANT_MSG_PREFIX}{ai_text}"))
        return msgs

    def format_window_for_summarizer(self) -> str:
        """Build a plain-text transcript of all turns for the summarizer LLM."""
        lines: list[str] = []
        for user_text, ai_text in self._turns:
            lines.append(f"[user msg]\n{user_text}")
            lines.append(f"[assistant msg]\n{ai_text}")
        return "\n\n".join(lines)

    def format_recent_messages(self) -> str:
        """Last up to five user/assistant turns as plain text (for planner/responder)."""
        lines: list[str] = []
        for user_text, ai_text in self._turns:
            lines.append(f"user: {user_text.strip()}")
            lines.append(f"assistant: {ai_text.strip()}")
        return "\n".join(lines).strip()

    async def summarize_async(self, llm) -> None:
        """Update rolling ``summary`` and ``user_key_facts`` from the conversation window."""
        conversation_transcript = self.format_window_for_summarizer()
        if not conversation_transcript.strip():
            logger.info("Summarizer: no conversation turns to summarize yet")
            return

        prior = (self.user_key_facts or "").strip()

        human_content = (
            f"Prior user_key_facts (merge new, correct outdated, dedupe; may be empty):\n"
            f"{prior or '(none)'}\n\n"
            f"--- CONVERSATION WINDOW (oldest → newest) ---\n"
            f"{conversation_transcript}\n"
            f"--- END OF CONVERSATION WINDOW ---"
        )

        logger.info(
            "Summarizer: processing %d turn(s), prior key_facts=%r",
            len(self._turns),
            prior or "(none)",
        )

        try:
            result = await llm.ainvoke([
                SystemMessage(content=SUMMARIZER_SYSTEM),
                HumanMessage(content=human_content),
            ])
            raw = (result.content or "").strip()
            logger.info("Summarizer raw LLM output: %s", raw[:500])

            summary_text, facts_text = _parse_summarizer_json(raw)

            if summary_text:
                self.summary = summary_text
                logger.info("Summarizer updated summary: %s", summary_text[:200])
            else:
                logger.warning("Summarizer produced empty summary from: %s", raw[:300])

            if facts_text is not None:
                self.user_key_facts = facts_text
                logger.info("Summarizer updated key_facts: %s", facts_text[:200])
        except Exception:
            logger.warning(
                "Summarization failed — keeping previous summary and key facts",
                exc_info=True,
            )


def _parse_summarizer_json(content: str) -> tuple[str, str | None]:
    """Return (summary, user_key_facts). ``facts`` is None if JSON could not be parsed for facts."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            summary_text = (data.get("summary") or "").strip()
            facts_text = (data.get("user_key_facts") or "").strip()
            return summary_text, facts_text
    except json.JSONDecodeError:
        logger.warning("Summarizer JSON parse failed for: %s", text[:300])
    return text, None


conversation_context = ConversationContext()
