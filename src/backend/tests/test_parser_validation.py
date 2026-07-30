"""Parser validation unit tests (no Docling runtime required)."""

from __future__ import annotations

from types import SimpleNamespace

from app.ingestion.parser import validate_conversion_result


def _status(name: str):
    return SimpleNamespace(name=name)


def test_success_accepted():
    conversion = SimpleNamespace(
        status=_status("SUCCESS"),
        errors=[],
        pages=[1, 2, 3],
        document=SimpleNamespace(pages={1: {}, 2: {}, 3: {}}),
    )
    result = validate_conversion_result(conversion, expected_pages=3)
    assert result.accepted is True


def test_partial_success_rejected():
    conversion = SimpleNamespace(
        status=_status("PARTIAL_SUCCESS"),
        errors=[SimpleNamespace(error_message="pipeline stopped")],
        pages=[1, 2],
        document=SimpleNamespace(pages={1: {}, 2: {}}),
    )
    result = validate_conversion_result(conversion, expected_pages=3)
    assert result.accepted is False
    assert result.status.endswith("PARTIAL_SUCCESS")
    assert result.reason


def test_page_mismatch_detected():
    conversion = SimpleNamespace(
        status=_status("SUCCESS"),
        errors=[],
        pages=[1, 2, 3, 4, 5, 6, 7, 8],
        document=SimpleNamespace(pages={i: {} for i in range(1, 9)}),
    )
    result = validate_conversion_result(conversion, expected_pages=17)
    assert result.accepted is False
    assert "Processed pages" in (result.reason or "")


def test_pipeline_errors_and_bad_alloc():
    conversion = SimpleNamespace(
        status=_status("FAILURE"),
        errors=[SimpleNamespace(error_message="std::bad_alloc")],
        pages=[],
        document=None,
    )
    result = validate_conversion_result(conversion)
    assert result.accepted is False
    assert "bad_alloc" in (result.reason or "").lower() or "FAILURE" in (result.reason or "")


def test_exporter_warnings_do_not_invalidate():
    # Exporter failures are recorded outside validate_conversion_result; core SUCCESS remains accepted.
    conversion = SimpleNamespace(
        status=_status("SUCCESS"),
        errors=[],
        pages=[1],
        document=SimpleNamespace(pages={1: {}}),
    )
    result = validate_conversion_result(conversion, expected_pages=1)
    assert result.accepted is True
    result.warnings.append("HTML export failed: MathML")
    assert result.accepted is True
