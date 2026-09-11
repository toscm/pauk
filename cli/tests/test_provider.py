"""Unit tests for LLM provider selection and the local-model wrapper.

These never download a model and never load llama.cpp: construction
is cheap (the model file is only touched on first chat/judge/tip),
and the download path is hard-blocked by PAUK_NO_MODEL_DOWNLOAD,
which conftest sets for the whole session.
"""

import pytest

from pauk.llm.hardware import MODELS
from pauk.llm.provider import (
    ClaudeCliProvider,
    LocalLlamaProvider,
    default_provider,
    models_cache_dir,
)


def test_local_provider_name_is_the_model_id():
    provider = LocalLlamaProvider(MODELS[3])   # qwen2.5-7b
    assert provider.name == "qwen2.5-7b"
    assert provider.model_path().name.endswith(".gguf")


def test_models_cache_dir_respects_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert models_cache_dir() == tmp_path / "pauk" / "models"


def test_ensure_model_blocked_in_tests(monkeypatch, tmp_path):
    # the file does not exist and downloads are disabled → clear error,
    # never an actual network fetch
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    provider = LocalLlamaProvider(MODELS[0])
    with pytest.raises(RuntimeError, match="download disabled"):
        provider.ensure_model()


def test_default_provider_prefers_local(monkeypatch):
    monkeypatch.setattr("pauk.llm.provider._local_runtime_available", lambda: True)
    provider = default_provider()
    assert isinstance(provider, LocalLlamaProvider)
    assert provider.name in {m.key for m in MODELS}


def test_default_provider_falls_back_to_claude(monkeypatch):
    monkeypatch.setattr("pauk.llm.provider._local_runtime_available", lambda: False)
    monkeypatch.setattr("pauk.llm.hardware.claude_cli_available", lambda: True)
    provider = default_provider()
    assert isinstance(provider, ClaudeCliProvider)
    assert provider.name == "claude-cli"


def test_default_provider_errors_when_nothing_available(monkeypatch):
    monkeypatch.setattr("pauk.llm.provider._local_runtime_available", lambda: False)
    monkeypatch.setattr("pauk.llm.hardware.claude_cli_available", lambda: False)
    with pytest.raises(RuntimeError, match="no LLM available"):
        default_provider()
