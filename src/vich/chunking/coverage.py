"""Best-effort check for whether a batch's chunks actually cover the
extracted page text handed to the VLM.

Grounding chunk_text in the PDF's own text (see `vich.parsing.extract_page_text`)
fixed *wording* fidelity, but a longer prompt has its own failure mode: the
model can simply drop a paragraph it was given, rather than paraphrasing
it (observed in practice -- an entire "1 Introduction" section vanished
from one run's output even though it was present, verbatim, in the
extracted text passed to the model). There's no way to force an LLM not to
do this, so this module gives visibility instead: a coarse word-overlap
signal to flag a batch that's plausibly missing content, rather than
letting it disappear silently.

This is deliberately coarse, not a guarantee: legitimate low coverage is
expected for a page that's mostly a figure or a table condensed into a few
summary sentences (though table_markdown usually recovers most of a
table's own words). It's meant to catch "a paragraph vanished," not to
police exact wording -- see `vich.chunking.normalize` / the prompt's own
"copy verbatim" rule for that.
"""

from __future__ import annotations

import re

# A batch below this fraction of covered words gets a warning printed for it.
LOW_COVERAGE_WARNING_THRESHOLD = 0.5

_WORD_RE = re.compile(r"[a-zA-Z0-9가-힣]{4,}")


def _significant_words(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)}


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
