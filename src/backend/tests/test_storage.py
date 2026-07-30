"""Unit tests for local storage backend."""

from __future__ import annotations

import pytest

from app.infrastructure.storage import LocalStorage, PathTraversalError


def test_save_and_read_bytes(tmp_path):
    store = LocalStorage(tmp_path)
    key = store.save_bytes("raw/papers/abc/source.pdf", b"%PDF-1.4 test")
    assert key == "raw/papers/abc/source.pdf"
    assert store.read_bytes(key) == b"%PDF-1.4 test"
    assert store.exists(key)


def test_json_round_trip(tmp_path):
    store = LocalStorage(tmp_path)
    key = store.save_json("normalized/papers/abc/meta.json", {"ok": True, "n": 1})
    assert store.read_json(key) == {"ok": True, "n": 1}


def test_path_traversal_rejected(tmp_path):
    store = LocalStorage(tmp_path)
    with pytest.raises(PathTraversalError):
        store.save_text("../secret.txt", "nope")
    with pytest.raises(PathTraversalError):
        store.read_bytes("foo/../../etc/passwd")


def test_list_and_delete(tmp_path):
    store = LocalStorage(tmp_path)
    store.save_text("a/b.txt", "hello")
    store.save_text("a/c.txt", "world")
    listed = store.list_objects("a")
    assert "a/b.txt" in listed
    assert "a/c.txt" in listed
    store.delete_object("a/b.txt")
    assert not store.exists("a/b.txt")
