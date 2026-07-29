"""Storage backends for PaperLens artifacts."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterable

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Base storage failure."""


class PathTraversalError(StorageError):
    """Raised when a key escapes the storage root."""


class ObjectNotFoundError(StorageError):
    """Raised when an object does not exist."""


def _normalize_key(key: str) -> str:
    cleaned = key.replace("\\", "/").lstrip("/")
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise PathTraversalError(f"Path traversal rejected for key: {key!r}")
    return "/".join(parts)


class StorageBackend(ABC):
    """Common storage interface."""

    @abstractmethod
    def save_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def save_text(self, key: str, text: str, encoding: str = "utf-8") -> str:
        raise NotImplementedError

    @abstractmethod
    def save_json(self, key: str, payload: Any) -> str:
        raise NotImplementedError

    @abstractmethod
    def read_bytes(self, key: str) -> bytes:
        raise NotImplementedError

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(key).decode(encoding)

    def read_json(self, key: str) -> Any:
        return json.loads(self.read_text(key))

    @abstractmethod
    def exists(self, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def list_objects(self, prefix: str = "") -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def delete_object(self, key: str) -> None:
        raise NotImplementedError


class LocalStorage(StorageBackend):
    """Filesystem storage with atomic writes."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        normalized = _normalize_key(key)
        path = (self.root / normalized).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise PathTraversalError(f"Path traversal rejected for key: {key!r}") from exc
        return path

    def save_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            Path(tmp_name).replace(path)
        except Exception:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return _normalize_key(key)

    def save_text(self, key: str, text: str, encoding: str = "utf-8") -> str:
        return self.save_bytes(key, text.encode(encoding), content_type="text/plain")

    def save_json(self, key: str, payload: Any) -> str:
        body = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        return self.save_text(key, body, encoding="utf-8")

    def read_bytes(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise ObjectNotFoundError(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def list_objects(self, prefix: str = "") -> list[str]:
        normalized = _normalize_key(prefix) if prefix else ""
        base = self.root / normalized if normalized else self.root
        if not base.exists():
            return []
        results: list[str] = []
        for path in base.rglob("*"):
            if path.is_file():
                rel = path.relative_to(self.root).as_posix()
                results.append(rel)
        return sorted(results)

    def delete_object(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()


class GCSStorage(StorageBackend):
    """Google Cloud Storage backend using Application Default Credentials."""

    def __init__(self, bucket_name: str, project_id: str | None = None) -> None:
        try:
            from google.cloud import storage
        except ImportError as exc:  # pragma: no cover
            raise StorageError("google-cloud-storage is required for GCS backend") from exc

        self.bucket_name = bucket_name
        self.client = storage.Client(project=project_id)
        self.bucket = self.client.bucket(bucket_name)

    def save_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        normalized = _normalize_key(key)
        blob = self.bucket.blob(normalized)
        blob.upload_from_string(data, content_type=content_type or "application/octet-stream")
        return normalized

    def save_text(self, key: str, text: str, encoding: str = "utf-8") -> str:
        return self.save_bytes(key, text.encode(encoding), content_type="text/plain; charset=utf-8")

    def save_json(self, key: str, payload: Any) -> str:
        body = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        return self.save_bytes(
            key,
            body.encode("utf-8"),
            content_type="application/json; charset=utf-8",
        )

    def read_bytes(self, key: str) -> bytes:
        normalized = _normalize_key(key)
        blob = self.bucket.blob(normalized)
        if not blob.exists():
            raise ObjectNotFoundError(key)
        return blob.download_as_bytes()

    def exists(self, key: str) -> bool:
        return self.bucket.blob(_normalize_key(key)).exists()

    def list_objects(self, prefix: str = "") -> list[str]:
        normalized = _normalize_key(prefix) if prefix else ""
        return sorted(blob.name for blob in self.client.list_blobs(self.bucket, prefix=normalized))

    def delete_object(self, key: str) -> None:
        normalized = _normalize_key(key)
        blob = self.bucket.blob(normalized)
        if blob.exists():
            blob.delete()


def get_storage(settings: Settings | None = None) -> StorageBackend:
    cfg = settings or get_settings()
    if cfg.storage_backend == "gcs":
        logger.info("Using GCS storage backend bucket=%s", cfg.gcs_bucket_name)
        return GCSStorage(bucket_name=cfg.gcs_bucket_name, project_id=cfg.gcp_project_id)
    root = cfg.local_storage_root
    if not root.is_absolute():
        root = Path.cwd() / root
    logger.info("Using local storage backend root=%s", root)
    return LocalStorage(root)


# Logical object key helpers -------------------------------------------------

def paper_raw_pdf_key(paper_id: str) -> str:
    return f"raw/papers/{paper_id}/source.pdf"


def paper_parsed_key(paper_id: str, name: str) -> str:
    return f"parsed/papers/{paper_id}/{name}"


def paper_normalized_key(paper_id: str, name: str) -> str:
    return f"normalized/papers/{paper_id}/{name}"


def paper_asset_key(paper_id: str, kind: str, name: str) -> str:
    return f"assets/papers/{paper_id}/{kind}/{name}"


def paper_enrichment_key(paper_id: str, kind: str, name: str) -> str:
    return f"enrichment/papers/{paper_id}/{kind}/{name}"


def paper_meta_key(paper_id: str) -> str:
    return f"normalized/papers/{paper_id}/meta.json"
