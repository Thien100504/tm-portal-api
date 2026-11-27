"""
One place that picks the AI endpoint and the model for every AI feature.

Any OpenAI-compatible endpoint works: NVIDIA (used whenever NVIDIA_API_KEY is
set), OpenAI, or a self-hosted server such as Ollama through OPENAI_BASE_URL.
AI_CHAT_MODEL / AI_TASK_MODEL override the models, so a model that the
provider retires is a config change instead of a code change.
"""

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI, OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

# Defaults for NVIDIA's hosted catalog (build.nvidia.com)
NVIDIA_CHAT_MODEL = "z-ai/glm-5.3-flash"  # fast, good at tool calling
NVIDIA_TASK_MODEL = "mistralai/mistral-large-4-1t-a52b"  # strong at strict JSON

# The chatbot may chain tool calls (find a task, then update it) up to this many times
MAX_TOOL_ROUNDS = 5


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.NVIDIA_API_KEY or settings.OPENAI_API_KEY)


def _endpoint() -> tuple[str | None, str]:
    settings = get_settings()
    if settings.NVIDIA_API_KEY:
        return settings.NVIDIA_BASE_URL, settings.NVIDIA_API_KEY
    return settings.OPENAI_BASE_URL or None, settings.OPENAI_API_KEY


def _model(override: str, nvidia_default: str) -> str:
    settings = get_settings()
    if override:
        return override
    return nvidia_default if settings.NVIDIA_API_KEY else settings.OPENAI_MODEL_NAME


def chat_model() -> str:
    """Model for the project chatbot (streams text and calls tools)."""
    return _model(get_settings().AI_CHAT_MODEL, NVIDIA_CHAT_MODEL)


def task_model() -> str:
    """Model for JSON jobs: insights, task breakdown, story point estimates."""
    return _model(get_settings().AI_TASK_MODEL, NVIDIA_TASK_MODEL)


def max_tokens() -> int:
    return get_settings().AI_MAX_TOKENS


def async_client() -> AsyncOpenAI:
    base_url, api_key = _endpoint()
    return AsyncOpenAI(base_url=base_url, api_key=api_key)


def sync_client() -> OpenAI:
    base_url, api_key = _endpoint()
    return OpenAI(base_url=base_url, api_key=api_key)


def warn_if_truncated(finish_reason: str | None, feature: str) -> None:
    """A reply cut at max_tokens looks like a broken model; say what really happened."""
    if finish_reason == "length":
        logger.warning(
            "AI %s reply was cut at max_tokens=%s; raise AI_MAX_TOKENS",
            feature,
            max_tokens(),
        )


_THINK_BLOCK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)
_CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def strip_reasoning(text: str | None) -> str:
    """Remove <think>...</think> blocks that reasoning models put before the answer."""
    return _THINK_BLOCK.sub("", text or "").strip()


def parse_json(text: str | None) -> Any:
    """
    Read the JSON value a model replied with, tolerating reasoning blocks,
    markdown fences and chatter around it. Raises ValueError when there is none.
    """
    content = strip_reasoning(text)
    fence = _CODE_FENCE.search(content)
    if fence:
        content = fence.group(1).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (content.find("{"), content.find("[")) if i != -1]
    if not starts:
        raise ValueError("AI reply contains no JSON")
    value, _ = json.JSONDecoder().raw_decode(content[min(starts) :])
    return value


def _partial_tag_length(text: str, tag: str) -> int:
    """How many trailing characters of text could be the start of tag."""
    for n in range(min(len(tag) - 1, len(text)), 0, -1):
        if tag.startswith(text[-n:]):
            return n
    return 0


class ReasoningFilter:
    """Drops <think>...</think> from a streamed reply, even when a tag is split across chunks."""

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self) -> None:
        self._pending = ""
        self._thinking = False

    def feed(self, chunk: str) -> str:
        """Add a streamed chunk; return the part that is safe to show."""
        self._pending += chunk
        visible: list[str] = []
        while True:
            tag = self.CLOSE if self._thinking else self.OPEN
            idx = self._pending.find(tag)
            if idx != -1:
                if not self._thinking:
                    visible.append(self._pending[:idx])
                self._pending = self._pending[idx + len(tag) :]
                self._thinking = not self._thinking
                continue
            keep = _partial_tag_length(self._pending, tag)
            cut = len(self._pending) - keep
            if not self._thinking:
                visible.append(self._pending[:cut])
            self._pending = self._pending[cut:]
            return "".join(visible)

    def flush(self) -> str:
        """Return what is left once the stream ends."""
        rest = "" if self._thinking else self._pending
        self._pending = ""
        return rest
