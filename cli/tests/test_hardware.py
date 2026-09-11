"""Unit tests for hardware detection and LLM model selection."""

from pauk.llm.hardware import (
    Hardware,
    choose_model,
    choose_provider,
    detect_hardware,
    recommended_threads,
)


def hw(ram, accel, cores=8, arch="arm64", system="Darwin"):
    return Hardware(
        ram_gb=ram, cores=cores, accelerator=accel, arch=arch, system=system
    )


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


def test_big_workstation_gets_the_largest_tier():
    # the user's box: 1 TB RAM, 112 cores, no GPU → the top curated tier
    model = choose_model(hw(1024, "none", cores=112, arch="x86_64", system="Linux"))
    assert model.key == "qwen2.5-32b"


def test_every_model_has_a_download_source():
    from pauk.llm.hardware import MODELS

    for m in MODELS:
        assert m.repo and m.filename and m.filename.endswith(".gguf")


def test_recommended_threads_caps_on_many_cores():
    # scaling flattens, so a 112-core box should not spawn 112 threads
    assert recommended_threads(hw(1024, "none", cores=112)) == 16
    assert recommended_threads(hw(16, "none", cores=4)) == 4
    assert recommended_threads(hw(8, "none", cores=1)) == 1


def test_detect_hardware_runs():
    detected = detect_hardware()
    assert detected.ram_gb > 0
    assert detected.cores >= 1
    assert detected.accelerator in ("metal", "cuda", "none")
