"""Optional LangSmith-compatible tracing hooks.

Tracing is disabled unless LANGSMITH_ENABLED and LANGSMITH_TRACING are true.
Failures never break request handling.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@contextmanager
def trace_span(name: str, metadata: dict[str, Any] | None = None, settings: Settings | None = None) -> Iterator[None]:
    cfg = settings or get_settings()
    if not (cfg.langsmith_enabled and cfg.langsmith_tracing):
        yield
        return
    try:
        # Soft dependency: only import when enabled.
        from langsmith import traceable  # type: ignore

        @traceable(name=name)
        def _inner() -> None:
            return None

        _inner()
        if metadata:
            logger.debug("langsmith span=%s meta_keys=%s", name, sorted(metadata.keys()))
    except Exception as exc:  # pragma: no cover - optional path
        logger.warning("LangSmith tracing skipped: %s", type(exc).__name__)
    yield
