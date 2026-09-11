"""Detect the local machine's capacity and choose a default LLM.

Quests and tips need a language model. pauk runs one locally by
default via llama.cpp (the `pauk[local]` extra) so there is no API
key, no subscription, and no always-on daemon. The model must fit
the machine, so we pick a tier from RAM and whether a GPU/Metal
accelerator is available; the core count sets how many threads
llama.cpp uses, not the tier. Example: an Apple-silicon Mac with
32 GB gets a 14B model on Metal; a 16 GB laptop without a GPU gets
a 3B; a tiny box gets a 0.5B; a 1 TB workstation gets the largest
curated tier.

When no local runtime is installed, the `claude` CLI is used as a
fallback (see pauk.llm.provider.default_provider).

This module is pure and testable: `choose_model` is a function of
a `Hardware` value, and `detect_hardware` is the only part that
touches the system.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Hardware:
    ram_gb: float
    cores: int               # logical CPU cores
    accelerator: str          # "metal" | "cuda" | "none"
    arch: str                 # "arm64" | "x86_64" | ...
    system: str               # "Darwin" | "Linux" | "Windows"


@dataclass(frozen=True)
class Model:
    key: str                  # short id, e.g. "qwen2.5-3b"
    label: str                # human name
    params_b: float           # billions of parameters
    min_ram_gb: float         # RAM the quantized model needs comfortably
    # Hugging Face GGUF source (repo + file). A Q4_K_M quant balances
    # size and quality; downloaded lazily on first use (see provider).
    repo: str | None = None
    filename: str | None = None


# Ordered small → large. Selection walks from the largest model the
# machine can comfortably run downwards. All are instruction-tuned
# Q4_K_M GGUFs from bartowski's well-known Hugging Face mirrors.
# Small, explicit, and easy to edit — add or retune a row here.
MODELS: list[Model] = [
    Model(
        "qwen2.5-0.5b", "Qwen2.5 0.5B Instruct", 0.5, 2,
        "bartowski/Qwen2.5-0.5B-Instruct-GGUF",
        "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
    ),
    Model(
        "llama3.2-1b", "Llama 3.2 1B Instruct", 1.0, 4,
        "bartowski/Llama-3.2-1B-Instruct-GGUF",
        "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
    ),
    Model(
        "llama3.2-3b", "Llama 3.2 3B Instruct", 3.0, 8,
        "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    ),
    Model(
        "qwen2.5-7b", "Qwen2.5 7B Instruct", 7.0, 16,
        "bartowski/Qwen2.5-7B-Instruct-GGUF",
        "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
    ),
    Model(
        "qwen2.5-14b", "Qwen2.5 14B Instruct", 14.0, 28,
        "bartowski/Qwen2.5-14B-Instruct-GGUF",
        "Qwen2.5-14B-Instruct-Q4_K_M.gguf",
    ),
    Model(
        "qwen2.5-32b", "Qwen2.5 32B Instruct", 32.0, 64,
        "bartowski/Qwen2.5-32B-Instruct-GGUF",
        "Qwen2.5-32B-Instruct-Q4_K_M.gguf",
    ),
]


def detect_hardware() -> Hardware:
    return Hardware(
        ram_gb=_total_ram_gb(),
        cores=os.cpu_count() or 1,
        accelerator=_accelerator(),
        arch=platform.machine().lower(),
        system=platform.system(),
    )


def _total_ram_gb() -> float:
    # avoid a psutil dependency: os.sysconf on POSIX, a fallback
    # elsewhere
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page = os.sysconf("SC_PAGE_SIZE")
        return round(pages * page / (1024 ** 3), 1)
    except (ValueError, AttributeError, OSError):
        pass
    if platform.system() == "Windows":
        try:
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MemStatus()
            stat.dwLength = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullTotalPhys / (1024 ** 3), 1)
        except Exception:  # noqa: BLE001
            pass
    return 8.0  # conservative default when detection fails


def _accelerator() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    # Apple silicon → Metal (llama.cpp uses it by default)
    if system == "Darwin" and machine in ("arm64", "aarch64"):
        return "metal"
    # NVIDIA GPU → CUDA, detected via nvidia-smi on PATH
    if shutil.which("nvidia-smi"):
        try:
            subprocess.run(
                ["nvidia-smi"], capture_output=True, timeout=5, check=True
            )
            return "cuda"
        except (subprocess.SubprocessError, OSError):
            pass
    return "none"


def claude_cli_available() -> bool:
    return shutil.which("claude") is not None


def choose_model(hw: Hardware) -> Model:
    """The largest model that comfortably fits, with a GPU/Metal
    machine allowed one tier higher than a CPU-only box of the same
    RAM (acceleration makes a bigger model usable in practice)."""
    budget = hw.ram_gb
    if hw.accelerator == "none":
        # without acceleration, leave more headroom — a big model is
        # painfully slow on CPU even if it technically fits
        budget = hw.ram_gb * 0.75
    fitting = [m for m in MODELS if m.min_ram_gb <= budget]
    return fitting[-1] if fitting else MODELS[0]


def recommended_threads(hw: Hardware) -> int:
    """Threads for llama.cpp on CPU. More cores help, but scaling
    flattens past ~16, so cap there to avoid oversubscription on a
    many-core box (the user's 112-core machine would gain nothing
    from 112 threads)."""
    return max(1, min(hw.cores, 16))


@dataclass(frozen=True)
class Provider:
    kind: str                 # "claude-cli" | "llama"
    detail: str               # human description
    model: Model | None       # the local model, when kind == "llama"


def choose_provider(hw: Hardware | None = None, prefer_local: bool = False) -> Provider:
    """Describe the quest LLM provider for a machine. Historically the
    `claude` CLI won when present; `prefer_local` (and the runtime
    priority in pauk.llm.provider.default_provider) favours the local
    model. This stays a pure describer used by `pauk doctor`."""
    hw = hw or detect_hardware()
    if not prefer_local and claude_cli_available():
        return Provider("claude-cli", "the installed `claude` CLI", None)
    model = choose_model(hw)
    accel = {"metal": "Metal", "cuda": "CUDA", "none": "CPU"}[hw.accelerator]
    return Provider(
        "llama",
        f"local {model.label} on {accel} "
        f"({hw.ram_gb:.0f} GB RAM, {hw.cores} cores)",
        model,
    )
