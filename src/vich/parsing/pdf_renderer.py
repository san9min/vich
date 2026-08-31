"""PDF -> page image rendering.

Ported from mafio/data/utils/visual_chunking.py (render_pdf_pages_to_base64,
safe_stem), generalized to drop mafio-specific naming.
"""

from __future__ import annotations

import base64
import re
import unicodedata
from pathlib import Path
from typing import TypedDict

import fitz  # PyMuPDF


class PageImage(TypedDict):
    """A single rendered PDF page, ready to send to a VLM."""

    page_num: int
    image_url: str


def slugify(text: str) -> str:
    """Normalize arbitrary text into an id-safe slug.

    Keeps word characters and Hangul (so a human can still recognize the
    source document), collapses everything else to underscores. Useful for
    deriving stable, filesystem/JSON-safe ids from document titles.
    """
    normalized = unicodedata.normalize("NFKC", text)
    slug = re.sub(r"[^\w가-힣.-]+", "_", normalized)
    return slug.strip("_")


def safe_stem(path: Path) -> str:
    """Slugify a file's stem (filename without extension)."""
    return slugify(path.stem)


def render_pdf_pages_to_base64(
    pdf_path: Path,
    page_start: int,
    page_end: int,
    zoom: float = 2.0,
) -> list[PageImage]:
    """Render a 1-based, inclusive page range of `pdf_path` to base64 PNGs.

    `zoom` scales the render matrix (2.0 ~= 144 DPI); higher values improve
    VLM legibility for dense tables/small print at the cost of more tokens.
    """
    doc = fitz.open(pdf_path)
    matrix = fitz.Matrix(zoom, zoom)

    images: list[PageImage] = []
    try:
        for page_num in range(page_start, page_end + 1):
            page = doc.load_page(page_num - 1)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img_bytes = pix.tobytes("png")
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")

            images.append(
                PageImage(
                    page_num=page_num,
                    image_url=f"data:image/png;base64,{img_b64}",
                )
            )
    finally:
        doc.close()

    return images


def count_pages(pdf_path: Path) -> int:
    """Return the total page count of a PDF."""
    doc = fitz.open(pdf_path)
    try:
        return doc.page_count
    finally:
        doc.close()
