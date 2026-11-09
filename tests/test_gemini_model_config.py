"""Generation and embeddings must use their environment-selected models verbatim."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv
from pydantic import BaseModel

from engine import gemini_client as gc
from engine.rewrite import llm


class Result(BaseModel):
    title: str


@pytest.mark.parametrize("model", ["gemini-2.5-flash", "new-generation-model"])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("kind", ["structured", "text", "rewrite"])
def test_all_generation_calls_follow_dotenv(monkeypatch, tmp_path, model, legacy, kind):
    env_file = tmp_path / ".env"
    env_file.write_text(f"GEMINI_MODEL={model}\n", encoding="utf-8")
    load_dotenv(env_file, override=True)
    monkeypatch.setenv("ENGINE_MODE", "live")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    # Old per-stage settings must not redirect generation to a different model.
    for stage in ["EXTRACT", "ANALYSIS", "REWRITE"]:
        monkeypatch.setenv(f"GEMINI_{stage}_MODEL", "obsolete-override")
    monkeypatch.setattr(gc, "_GENAI_NEW", True)
    monkeypatch.setattr(gc, "_GENAI_LEGACY", legacy)
    response = SimpleNamespace(text='{"title":"synthetic"}', candidates=[])
    client = MagicMock()
    client.models.generate_content.return_value = response
    monkeypatch.setattr("google.genai.Client", MagicMock(return_value=client))
    legacy_factory = MagicMock()
    if legacy and kind != "rewrite":
        client.models.generate_content.side_effect = RuntimeError("synthetic SDK error")
        legacy_factory.return_value.generate_content.return_value = response
        monkeypatch.setattr("google.generativeai.configure", MagicMock())
        monkeypatch.setattr("google.generativeai.GenerativeModel", legacy_factory)

    if kind == "structured":
        assert gc.generate_structured_json("synthetic", Result).title == "synthetic"
    elif kind == "text":
        assert gc.generate_gemini_text("synthetic") == response.text
    else:
        monkeypatch.setattr(llm, "_get_client", lambda: client)
        assert llm.call_structured(
            system="synthetic", user="synthetic", tool_name="result",
            tool_description="synthetic", tool_schema=Result.model_json_schema(),
        ) == {"title": "synthetic"}

    client.models.generate_content.assert_called_once()
    assert client.models.generate_content.call_args.kwargs["model"] == model
    if legacy and kind != "rewrite":
        legacy_factory.assert_called_once()
        assert legacy_factory.call_args.kwargs["model_name"] == model


@pytest.mark.parametrize("kind", ["structured", "text"])
def test_provider_failure_never_tries_a_different_model(monkeypatch, kind):
    monkeypatch.setenv("ENGINE_MODE", "live")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    monkeypatch.setenv("GEMINI_MODEL", "selected-model")
    monkeypatch.setattr(gc, "_GENAI_NEW", True)
    monkeypatch.setattr(gc, "_GENAI_LEGACY", False)
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("synthetic provider error")
    monkeypatch.setattr("google.genai.Client", MagicMock(return_value=client))
    with pytest.raises(RuntimeError):
        if kind == "structured":
            gc.generate_structured_json("synthetic", Result)
        else:
            gc.generate_gemini_text("synthetic")
    client.models.generate_content.assert_called_once()
    assert client.models.generate_content.call_args.kwargs["model"] == "selected-model"


@pytest.mark.parametrize("value", [None, "", "  "])
@pytest.mark.parametrize("embedding", [False, True])
def test_missing_model_is_explicit_instead_of_using_a_hardcoded_default(monkeypatch, value, embedding):
    setting = "GEMINI_EMBEDDING_MODEL" if embedding else "GEMINI_MODEL"
    if value is None:
        monkeypatch.delenv(setting, raising=False)
    else:
        monkeypatch.setenv(setting, value)
    getter = gc.get_embedding_model if embedding else gc.get_default_gemini_model
    with pytest.raises(RuntimeError, match=f"{setting} is not set"):
        getter()


@pytest.mark.parametrize("legacy", [False, True])
def test_embedding_sdks_use_the_separate_environment_setting(monkeypatch, legacy):
    monkeypatch.setenv("ENGINE_MODE", "live")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    monkeypatch.setenv("GEMINI_EMBEDDING_MODEL", "selected-embedding-model")
    monkeypatch.setattr(gc, "_GENAI_NEW", True)
    monkeypatch.setattr(gc, "_GENAI_LEGACY", legacy)
    client = MagicMock()
    client.models.embed_content.return_value = SimpleNamespace(
        embeddings=[SimpleNamespace(values=[0.1])],
    )
    monkeypatch.setattr("google.genai.Client", MagicMock(return_value=client))
    legacy_embed = MagicMock(return_value={"embedding": [0.1]})
    if legacy:
        client.models.embed_content.side_effect = RuntimeError("synthetic SDK error")
        monkeypatch.setattr("google.generativeai.configure", MagicMock())
        monkeypatch.setattr("google.generativeai.embed_content", legacy_embed)
    assert gc.get_embedding("synthetic") == [0.1]
    assert client.models.embed_content.call_args.kwargs["model"] == "selected-embedding-model"
    if legacy:
        assert legacy_embed.call_args.kwargs["model"] == "selected-embedding-model"
