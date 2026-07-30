from __future__ import annotations

from app.infrastructure import accelerator


def test_accelerator_status_reports_usable_cuda(monkeypatch):
    monkeypatch.setattr(
        accelerator,
        "_probe_torch",
        lambda: {
            "torch_cuda_available": True,
            "torch_cuda_version": "12.6",
            "gpu_name": "NVIDIA L4",
            "gpu_count": 1,
        },
    )
    accelerator.accelerator_status.cache_clear()
    status = accelerator.accelerator_status("cuda")

    assert status["requested_device"] == "cuda"
    assert status["active_device"] == "cuda"
    assert status["gpu_usable"] is True
    assert status["gpu_name"] == "NVIDIA L4"
    accelerator.accelerator_status.cache_clear()


def test_accelerator_status_exposes_cpu_fallback(monkeypatch):
    monkeypatch.setattr(
        accelerator,
        "_probe_torch",
        lambda: {
            "torch_cuda_available": False,
            "torch_cuda_version": None,
            "gpu_name": None,
            "gpu_count": 0,
        },
    )
    accelerator.accelerator_status.cache_clear()
    status = accelerator.accelerator_status("cuda")

    assert status["requested_device"] == "cuda"
    assert status["active_device"] == "cpu"
    assert status["gpu_usable"] is False
    accelerator.accelerator_status.cache_clear()
