"""Detect the local machine's capacity and choose a default LLM.

Quests need a language model. The best provider, when present, is
the `claude` CLI (uses the user's existing login, no download).
Otherwise pauk can run a local GGUF model via llama.cpp — but the
model must fit the machine, so we pick a tier from RAM and whether
a GPU/accelerator is available. Example: an Apple-silicon Mac with
32 GB gets a 7B model; a 16 GB laptop without a GPU gets a 3B; a
tiny box gets a 1B.

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
    accelerator: str          # "metal" | "cuda" | "none"
    arch: str                 # "arm64" | "x86_64" | ...
    system: str               # "Darwin" | "Linux" | "Windows"


@dataclass(frozen=True)
class Model:
    key: str                  # short id, e.g. "qwen2.5-3b"
    label: str                # human name
    params_b: float           # billions of parameters
    min_ram_gb: float         # RAM the quantized model needs comfortably
    # a resumable download URL is filled in when we actually wire
    # llama.cpp; kept out of the selection logic on purpose
    gguf: str | None = None


# Ordered small → large. Selection walks from the largest model
# the machine can comfortably run downwards.
MODELS: list[Model] = [
    Model("qwen2.5-0.5b", "Qwen2.5 0.5B Instruct", 0.5, 2),
    Model("llama3.2-1b", "Llama 3.2 1B Instruct", 1.0, 4),
    Model("llama3.2-3b", "Llama 3.2 3B Instruct", 3.0, 8),
    Model("qwen2.5-7b", "Qwen2.5 7B Instruct", 7.0, 16),
    Model("qwen2.5-14b", "Qwen2.5 14B Instruct", 14.0, 28),
]


def detect_hardware() -> Hardware:
    return Hardware(
        ram_gb=_total_ram_gb(),
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


@dataclass(frozen=True)
class Provider:
    kind: str                 # "claude-cli" | "llama"
    detail: str               # human description
    model: Model | None       # the local model, when kind == "llama"


def choose_provider(hw: Hardware | None = None, prefer_local: bool = False) -> Provider:
    """Pick the quest LLM provider. The `claude` CLI wins when
    available (no download, strongest model) unless the user forces
    local; otherwise a local model sized to the machine."""
    hw = hw or detect_hardware()
    if not prefer_local and claude_cli_available():
        return Provider("claude-cli", "the installed `claude` CLI", None)
    model = choose_model(hw)
    accel = {"metal": "Metal", "cuda": "CUDA", "none": "CPU"}[hw.accelerator]
    return Provider(
        "llama",
        f"local {model.label} on {accel} ({hw.ram_gb:.0f} GB RAM)",
        model,
    )
