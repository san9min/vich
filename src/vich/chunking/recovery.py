"""Find content a batch's chunks failed to cover, so it can be recovered
instead of merely flagged.

`vich.chunking.coverage.coverage_ratio` measures a *batch's* overall word
overlap, but a batch's average can stay comfortably high even while one
whole paragraph is missing -- observed in practice: a paragraph vanished
from a batch that still scored 69% coverage, well above what looked like a
reasonable warning threshold. A warning at that granularity is visibility,
not a fix. This module checks block by block instead (PyMuPDF's own
paragraph-ish segmentation, see `vich.parsing.extract_page_blocks`) and
returns the specific blocks that look dropped, so the pipeline can insert
a fallback chunk built directly from each one's verbatim text.
"""

from __future__ import annotations

from vich.chunking.coverage import coverage_ratio, significant_word_count
from vich.parsing.pdf_renderer import PageBlock

# A block below this word count is presumed to be a header/footer/page
# number/caption fragment, not a paragraph worth recovering on its own.
MIN_RECOVERABLE_WORDS = 15

# A block at or above this coverage is presumed to already be represented
# in some chunk (possibly reworded, or split across a couple of chunks),
# not dropped outright.
RECOVERY_COVERAGE_THRESHOLD = 0.3


def find_missed_blocks(blocks: list[PageBlock], chunk_texts: list[str]) -> list[PageBlock]:
    """Blocks substantial enough to matter whose words barely show up
    anywhere in `chunk_texts` -- plausibly dropped by the VLM entirely."""
    return [
        block
        for block in blocks
        if significant_word_count(block["text"]) >= MIN_RECOVERABLE_WORDS
        and coverage_ratio(block["text"], chunk_texts) < RECOVERY_COVERAGE_THRESHOLD
    ]
