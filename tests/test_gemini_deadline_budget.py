"""Each SDK fallback must use the remaining shared budget, with no hidden retries."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from engine import gemini_client as gc


class Result(BaseModel):
    title: str


@pytest.mark.parametrize("kind", ["structured", "text", "embedding"])
@pytest.mark.parametrize("spent", [0.25, 1.1])
def test_sdk_fallback_respects_remaining_budget(monkeypatch, kind, spent):
    monkeypatch.setenv("ENGINE_MODE", "live")
    monkeypatch.setattr(gc, "get_gemini_api_key", lambda: "synthetic-key")
    monkeypatch.setattr(gc, "_GENAI_NEW", True)
    monkeypatch.setattr(gc, "_GENAI_LEGACY", True)
    clock = [0.0]
    monkeypatch.setattr(gc, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    new_client = MagicMock()
    client_factory = MagicMock(return_value=new_client)
    legacy_model = MagicMock()
    legacy_model.generate_content.return_value.text = '{"title":"synthetic"}'
    legacy_embedding = MagicMock(return_value={"embedding": [0.1]})

    def modern_failure(**kwargs):
        clock[0] = spent
        raise RuntimeError("synthetic provider error")

    new_client.models.generate_content.side_effect = modern_failure
    new_client.models.embed_content.side_effect = modern_failure
    monkeypatch.setattr("google.genai.Client", client_factory)
    monkeypatch.setattr("google.generativeai.configure", MagicMock())
    monkeypatch.setattr("google.generativeai.GenerativeModel", MagicMock(return_value=legacy_model))
    monkeypatch.setattr("google.generativeai.embed_content", legacy_embedding)

    def invoke():
        if kind == "structured":
            return gc.generate_structured_json("synthetic", Result, timeout=1)
        if kind == "text":
            return gc.generate_gemini_text("synthetic", timeout=1)
        return gc.get_embedding("synthetic", timeout=1)

    fallback = legacy_embedding if kind == "embedding" else legacy_model.generate_content
    if spent >= 1:
        with pytest.raises(TimeoutError):
            invoke()
        fallback.assert_not_called()
    else:
        invoke()
        options = fallback.call_args.kwargs["request_options"]
        assert options["timeout"] == pytest.approx(0.75)
        assert options["retry"] is None
    assert client_factory.call_args.kwargs["http_options"].retry_options.attempts == 1


def test_next_model_does_not_restart_expired_budget(monkeypatch):
    monkeypatch.setenv("ENGINE_MODE", "live")
    monkeypatch.setattr(gc, "get_gemini_api_key", lambda: "synthetic-key")
    monkeypatch.setattr(gc, "_GENAI_NEW", True)
    monkeypatch.setattr(gc, "_GENAI_LEGACY", False)
    monkeypatch.setattr(gc, "FALLBACK_MODELS", ["fallback-model"])
    clock = [0.0]
    monkeypatch.setattr(gc, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    client = MagicMock()

    def fail(**kwargs):
        clock[0] = 1.1
        raise RuntimeError("synthetic provider error")

    client.models.generate_content.side_effect = fail
    monkeypatch.setattr("google.genai.Client", MagicMock(return_value=client))
    with pytest.raises(TimeoutError):
        gc.generate_gemini_text("synthetic", model_name="preferred-model", timeout=1)
    assert client.models.generate_content.call_count == 1
