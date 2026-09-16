"""Thin Anthropic wrapper shared by detect/generate/validate.

One structured-output helper (`call_structured`) backs all three LLM call
sites: it forces the model to answer through a single tool call, so the
response is a validated JSON object, never prose to regex out of a message.
Every call site owns its own prompt and tool schema
(`engine/rewrite/prompts.py`); this module owns talking to the API and nothing
about F5's rules.

Never imports from `api/` (`engine/README.md`, "the internals rule": nothing
in `engine/` knows about FastAPI, a locale, or a request). The Anthropic SDK
reads `ANTHROPIC_API_KEY` from the environment on its own (see
`.env.example`), so this module needs no config object passed in.
"""

from __future__ import annotations

from typing import Any

import anthropic

MODEL = "claude-sonnet-5"

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Lazy singleton: importing this module — and running the deterministic
    half of the validator suite (`tests/test_rewrite_validator.py`) — must not
    require `ANTHROPIC_API_KEY` to be set."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def call_structured(
    *,
    system: str,
    user: str,
    tool_name: str,
    tool_description: str,
    tool_schema: dict[str, Any],
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """Call the model and force its answer through one tool call.

    Returns the tool call's `input` dict, already shaped by `tool_schema` — the
    caller parses it with a Pydantic model and gets Pydantic's own error
    messages for anything the model got wrong, rather than a JSON parse error
    on free text.
    """
    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[{"name": tool_name, "description": tool_description, "input_schema": tool_schema}],
        tool_choice={"type": "tool", "name": tool_name},
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            return dict(block.input)
    raise RuntimeError(f"Anthropic response had no {tool_name!r} tool_use block: {response.content!r}")
