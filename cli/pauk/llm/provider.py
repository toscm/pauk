"""LLM providers for quests.

A provider does two things: play a character for one dialog turn
(`chat`) and judge whether the user succeeded (`judge`). The quest
flow depends only on this small interface, so it is trivially
faked in tests — no real model is ever needed in CI.

The default real provider drives the `claude` CLI, which uses the
user's existing login (no API key, no download). A local llama
provider is selected on machines without the CLI once the runtime
is wired (see pauk.llm.hardware); until then it raises a clear
"not available yet" error.
"""

from __future__ import annotations

import json
import subprocess
from typing import Protocol


class Provider(Protocol):
    name: str

    def chat(self, system: str, messages: list[dict]) -> str:
        """One in-character assistant reply given the conversation
        so far (messages are {'role': 'user'|'assistant', 'content'})."""
        ...

    def judge(self, criteria: str, transcript: list[dict]) -> bool:
        """Decide whether the transcript satisfies the criteria."""
        ...


def _render(system: str, messages: list[dict]) -> str:
    lines = [system, ""]
    for m in messages:
        who = "Customer" if m["role"] == "user" else "You"
        lines.append(f"{who}: {m['content']}")
    lines.append("You:")
    return "\n".join(lines)


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
        convo = "\n".join(
            f"{'Customer' if m['role'] == 'user' else 'Character'}: {m['content']}"
            for m in transcript
        )
        prompt = (
            "You are grading a role-play language exercise. Success "
            f"criteria:\n{criteria}\n\nTranscript:\n{convo}\n\n"
            'Reply with a single JSON object {"success": true|false} '
            "and nothing else."
        )
        out = self._run(prompt)
        try:
            start = out.index("{")
            end = out.rindex("}") + 1
            return bool(json.loads(out[start:end]).get("success"))
        except (ValueError, json.JSONDecodeError):
            # if the judge is unclear, do not award success
            return False


class LocalLlamaProvider:
    """Placeholder for a bundled llama.cpp model. The model tier is
    already chosen by pauk.llm.hardware; wiring the download and
    inference is tracked in issues/0009."""

    name = "llama"

    def __init__(self, model_label: str):
        self._model_label = model_label

    def _unavailable(self):
        raise RuntimeError(
            f"local model ({self._model_label}) is not wired yet — "
            "install the `claude` CLI to run quests now (see `pauk doctor`)"
        )

    def chat(self, system: str, messages: list[dict]) -> str:
        self._unavailable()

    def judge(self, criteria: str, transcript: list[dict]) -> bool:
        self._unavailable()


def default_provider() -> Provider:
    """Pick a provider from the machine (claude CLI preferred)."""
    from pauk.llm.hardware import choose_provider

    chosen = choose_provider()
    if chosen.kind == "claude-cli":
        return ClaudeCliProvider()
    return LocalLlamaProvider(chosen.model.label if chosen.model else "unknown")
