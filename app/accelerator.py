"""Runtime accelerator diagnostics for Docling workloads."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import Settings, get_settings


def _probe_torch() -> dict[str, Any]:
    try:
        import torch

        available = bool(torch.cuda.is_available())
        return {
            "torch_cuda_available": available,
            "torch_cuda_version": torch.version.cuda,
            "gpu_name": torch.cuda.get_device_name(0) if available else None,
            "gpu_count": torch.cuda.device_count() if available else 0,
        }
    except Exception as exc:
        return {
            "torch_cuda_available": False,
            "torch_cuda_version": None,
            "gpu_name": None,
            "gpu_count": 0,
            "probe_error": type(exc).__name__,
        }


@lru_cache(maxsize=4)
def accelerator_status(requested_device: str | None = None) -> dict[str, Any]:
    settings: Settings | None = None
    if requested_device is None:
        settings = get_settings()
        requested_device = settings.docling_accelerator_device
    probe = _probe_torch()
    active = "cuda" if probe["torch_cuda_available"] else "cpu"
    return {
        "requested_device": requested_device,
        "active_device": active,
        "gpu_usable": active == "cuda",
        **probe,
    }
