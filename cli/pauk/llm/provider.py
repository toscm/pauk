"""LLM providers for quests and tips.

A provider does three things: play a character for one dialog turn
(`chat`), judge whether the user succeeded (`judge`), and give a
one-line hint for a question (`tip`). The quiz/quest flow depends
only on this small interface, so it is trivially faked in tests —
no real model is ever needed in CI.

The default real provider runs a local GGUF model in-process via
llama.cpp (the `pauk[local]` extra): no API key, no subscription,
no daemon. The model tier is chosen from the machine (see
pauk.llm.hardware) and downloaded lazily on first use into
~/.cache/pauk/models/. When no local runtime is installed, the
`claude` CLI is used instead; if neither is available, a clear
error is raised.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Protocol

from pauk.llm.hardware import Model


class Provider(Protocol):
    name: str

    def chat(self, system: str, messages: list[dict]) -> str:
        """One in-character assistant reply given the conversation
        so far (messages are {'role': 'user'|'assistant', 'content'})."""
        ...

    def judge(self, criteria: str, transcript: list[dict]) -> bool:
        """Decide whether the transcript satisfies the criteria."""
        ...

    def tip(self, question: str) -> str:
        """A short hint for a question that does NOT reveal the answer."""
        ...


TIP_SYSTEM = (
    "You are a helpful tutor. Give ONE short hint (at most one "
    "sentence) that nudges the learner toward the answer to the "
    "question below WITHOUT revealing it. Reply with the hint only."
)


def _render(system: str, messages: list[dict]) -> str:
    lines = [system, ""]
    for m in messages:
        who = "Customer" if m["role"] == "user" else "You"
        lines.append(f"{who}: {m['content']}")
    lines.append("You:")
    return "\n".join(lines)


def _judge_prompt(criteria: str, transcript: list[dict]) -> str:
    convo = "\n".join(
        f"{'Customer' if m['role'] == 'user' else 'Character'}: {m['content']}"
        for m in transcript
    )
    return (
        "You are grading a role-play language exercise. Success "
        f"criteria:\n{criteria}\n\nTranscript:\n{convo}\n\n"
        'Reply with a single JSON object {"success": true|false} '
        "and nothing else."
    )


def _parse_verdict(out: str) -> bool:
    try:
        start = out.index("{")
        end = out.rindex("}") + 1
        return bool(json.loads(out[start:end]).get("success"))
    except (ValueError, json.JSONDecodeError):
        # if the judge is unclear, do not award success
        return False


class ClaudeCliProvider:
    """Drives the `claude` CLI in one-shot print mode (`claude -p`).
    Each turn is a stateless call carrying the whole transcript, so
    no session state is needed."""

    name = "claude-cli"

    def __init__(self, binary: str = "claude"):
        self._binary = binary

    def _run(self, prompt: str) -> str:
        proc = subprocess.run(
            [self._binary, "-p", prompt],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI failed: {proc.stderr.strip()[:200]}")
        return proc.stdout.strip()

    def chat(self, system: str, messages: list[dict]) -> str:
        return self._run(_render(system, messages))

    def judge(self, criteria: str, transcript: list[dict]) -> bool:
        return _parse_verdict(self._run(_judge_prompt(criteria, transcript)))

    def tip(self, question: str) -> str:
        return self._run(f"{TIP_SYSTEM}\n\nQuestion:\n{question}")


def models_cache_dir() -> Path:
    """Where downloaded GGUF models live (respects XDG_CACHE_HOME)."""
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "pauk" / "models"


class LocalLlamaProvider:
    """Runs a local GGUF model in-process with llama.cpp. The model
    is chosen from the machine (pauk.llm.hardware) and downloaded on
    first use; llama.cpp is imported lazily so the base install stays
    light and tests never need the runtime.

    `name` is the model id (e.g. "qwen2.5-7b") so the status bar can
    show which model is answering."""

    def __init__(self, model: Model, n_threads: int | None = None,
                 n_gpu_layers: int = 0):
        self.model = model
        self.name = model.key
        self._n_threads = n_threads
        self._n_gpu_layers = n_gpu_layers
        self._llm = None  # lazily loaded llama_cpp.Llama

    # --- model file -------------------------------------------------
    def model_path(self) -> Path:
        return models_cache_dir() / self.model.filename

    def ensure_model(self) -> Path:
        """Download the GGUF into the cache on first use. Never runs in
        tests: PAUK_NO_MODEL_DOWNLOAD hard-blocks it, and the provider
        is faked there anyway."""
        path = self.model_path()
        if path.exists():
            return path
        if os.environ.get("PAUK_NO_MODEL_DOWNLOAD"):
            raise RuntimeError(
                "model download disabled (PAUK_NO_MODEL_DOWNLOAD set)"
            )
        import urllib.request

        path.parent.mkdir(parents=True, exist_ok=True)
        url = (
            f"https://huggingface.co/{self.model.repo}"
            f"/resolve/main/{self.model.filename}?download=true"
        )
        tmp = path.with_suffix(path.suffix + ".part")
        # download to a .part file and rename, so an interrupted
        # download never looks like a complete model
        with urllib.request.urlopen(url) as resp, open(tmp, "wb") as out:
            while chunk := resp.read(1 << 20):
                out.write(chunk)
        tmp.rename(path)
        return path

    def _ensure_loaded(self):
        if self._llm is not None:
            return self._llm
        try:
            from llama_cpp import Llama
        except ImportError as exc:  # pragma: no cover - needs the extra
            raise RuntimeError(
                "local LLM runtime not installed — run "
                "`pip install 'pauk[local]'` or install the `claude` CLI"
            ) from exc
        path = self.ensure_model()
        self._llm = Llama(
            model_path=str(path),
            n_ctx=4096,
            n_threads=self._n_threads,
            n_gpu_layers=self._n_gpu_layers,
            verbose=False,
        )
        return self._llm

    def _complete(self, messages: list[dict], max_tokens: int) -> str:
        """One chat completion, streamed from llama.cpp (lower
        time-to-first-token and steady memory) and joined."""
        llm = self._ensure_loaded()
        pieces: list[str] = []
        for part in llm.create_chat_completion(
            messages=messages, max_tokens=max_tokens, temperature=0.7,
            stream=True,
        ):
            delta = part["choices"][0]["delta"].get("content")
            if delta:
                pieces.append(delta)
        return "".join(pieces).strip()

    # --- provider interface ----------------------------------------
    def chat(self, system: str, messages: list[dict]) -> str:
        return self._complete(
            [{"role": "system", "content": system}, *messages], max_tokens=512
        )

    def judge(self, criteria: str, transcript: list[dict]) -> bool:
        out = self._complete(
            [{"role": "user", "content": _judge_prompt(criteria, transcript)}],
            max_tokens=64,
        )
        return _parse_verdict(out)

    def tip(self, question: str) -> str:
        return self._complete(
            [
                {"role": "system", "content": TIP_SYSTEM},
                {"role": "user", "content": question},
            ],
            max_tokens=128,
        )


def _local_runtime_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("llama_cpp") is not None


def default_provider() -> Provider:
    """Pick a provider from the machine. A local llama model is the
    default when its runtime is installed; otherwise the `claude` CLI;
    otherwise a clear error. Tests inject a fake, so this never runs
    in CI."""
    from pauk.llm.hardware import (
        choose_model,
        claude_cli_available,
        detect_hardware,
        recommended_threads,
    )

    if _local_runtime_available():
        hw = detect_hardware()
        model = choose_model(hw)
        return LocalLlamaProvider(
            model,
            n_threads=recommended_threads(hw),
            n_gpu_layers=-1 if hw.accelerator in ("metal", "cuda") else 0,
        )
    if claude_cli_available():
        return ClaudeCliProvider()
    raise RuntimeError(
        "no LLM available — install the local runtime with "
        "`pip install 'pauk[local]'` or install the `claude` CLI "
        "(see `pauk doctor`)"
    )
