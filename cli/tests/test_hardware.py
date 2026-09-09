"""Unit tests for hardware detection and LLM model selection."""

from pauk.llm.hardware import (
    Hardware,
    choose_model,
    choose_provider,
    detect_hardware,
)


def hw(ram, accel, arch="arm64", system="Darwin"):
    return Hardware(ram_gb=ram, accelerator=accel, arch=arch, system=system)


def test_macbook_m2_32gb_gets_a_large_model():
    model = choose_model(hw(32, "metal"))
    assert model.params_b >= 7   # 7B or larger fits comfortably


def test_16gb_no_gpu_gets_a_smaller_model_than_m2():
    weak = choose_model(hw(16, "none", arch="x86_64", system="Windows"))
    strong = choose_model(hw(32, "metal"))
    assert weak.params_b < strong.params_b
    # 16 GB without a GPU: 0.75*16 = 12 → the 3B tier (min 8), not 7B
    assert weak.key == "llama3.2-3b"


def test_tiny_machine_gets_the_smallest():
    assert choose_model(hw(2, "none")).key == "qwen2.5-0.5b"


def test_gpu_allows_a_bigger_model_than_cpu_same_ram():
    gpu = choose_model(hw(16, "cuda", arch="x86_64", system="Linux"))
    cpu = choose_model(hw(16, "none", arch="x86_64", system="Linux"))
    assert gpu.params_b >= cpu.params_b
    assert gpu.key == "qwen2.5-7b"   # 16 GB + CUDA reaches the 7B tier


def test_provider_prefers_claude_cli(monkeypatch):
    monkeypatch.setattr("pauk.llm.hardware.claude_cli_available", lambda: True)
    provider = choose_provider(hw(8, "none"))
    assert provider.kind == "claude-cli"
    assert provider.model is None


def test_provider_falls_back_to_local(monkeypatch):
    monkeypatch.setattr("pauk.llm.hardware.claude_cli_available", lambda: False)
    provider = choose_provider(hw(32, "metal"))
    assert provider.kind == "llama"
    assert provider.model is not None
    assert "Metal" in provider.detail


def test_prefer_local_ignores_claude(monkeypatch):
    monkeypatch.setattr("pauk.llm.hardware.claude_cli_available", lambda: True)
    provider = choose_provider(hw(32, "metal"), prefer_local=True)
    assert provider.kind == "llama"


def test_detect_hardware_runs():
    detected = detect_hardware()
    assert detected.ram_gb > 0
    assert detected.accelerator in ("metal", "cuda", "none")
