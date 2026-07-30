"""Asset geometry helpers."""

from __future__ import annotations

from app.ingestion.assets import bbox_to_pil_crop
from app.schemas import BoundingBox


def test_bottomleft_to_pillow_crop():
    bbox = BoundingBox(l=10, t=90, r=50, b=70, coord_origin="BOTTOMLEFT")
    # page height 100, image 100x100
    left, upper, right, lower = bbox_to_pil_crop(
        bbox,
        (100, 100),
        page_width=100,
        page_height=100,
        padding=0,
    )
    assert left == 10
    assert right == 50
    # top_from_bottom=90 => upper=10; bottom_from_bottom=70 => lower=30
    assert upper == 10
    assert lower == 30


def test_padding_and_clamping():
    bbox = BoundingBox(l=0, t=10, r=5, b=0, coord_origin="BOTTOMLEFT")
    left, upper, right, lower = bbox_to_pil_crop(
        bbox,
        (20, 20),
        page_width=20,
        page_height=20,
        padding=4,
    )
    assert left == 0
    assert upper >= 0
    assert right <= 20
    assert lower <= 20
