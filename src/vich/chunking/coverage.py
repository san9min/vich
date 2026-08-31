"""Word-overlap primitives used by `vich.chunking.recovery` to tell whether
a block of source text made it into a batch's chunks.

Grounding chunk_text in the PDF's own text (see `vich.parsing.extract_page_text`)
fixed *wording* fidelity, but a longer prompt has its own failure mode: the
model can simply drop a paragraph it was given, rather than paraphrasing
it (observed in practice -- an entire "1 Introduction" section vanished
from one run's output even though it was present, verbatim, in the
extracted text passed to the model, from a batch whose *overall* coverage
still looked fine). `coverage_ratio` here is deliberately coarse -- it's
not meant to police exact wording (see `vich.chunking.normalize` / the
prompt's own "copy verbatim" rule for that) -- but checked per paragraph
block rather than per batch, it's precise enough to catch a block that
really did vanish. See `vich.chunking.recovery` for where that check
actually gets acted on.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-zA-Z0-9가-힣]{4,}")


def _significant_words(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)}


def significant_word_count(text: str) -> int:
    """Count of distinct significant (4+ char) words in `text`. Used to
    tell a substantial paragraph apart from a short header/footer/caption
    fragment -- see `vich.chunking.recovery`."""
    return len(_significant_words(text))


def coverage_ratio(extracted_text: str, chunk_texts: list[str]) -> float:
    """Fraction of `extracted_text`'s distinct significant (4+ char) words
    that appear somewhere across `chunk_texts`.

    Returns 1.0 when `extracted_text` has no significant words (e.g. an
    empty or scanned page) -- there's nothing to cover, so it can't be
    under-covered.
    """
    source_words = _significant_words(extracted_text)
    if not source_words:
        return 1.0

    covered_words = _significant_words(" ".join(chunk_texts))
    return len(source_words & covered_words) / len(source_words)
