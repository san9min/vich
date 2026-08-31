# Example: Docling paper

A worked example of what `vich` produces, end to end, run against a real,
dense, two-column academic PDF.

`docling_example.pdf` is *"Docling: An Efficient Open-Source Toolkit for
AI-driven Document Conversion"* (Livathinos, Auer, et al., IBM Research,
[arXiv:2501.17887v1](https://arxiv.org/abs/2501.17887v1)), licensed
[CC BY 4.0](http://creativecommons.org/licenses/by/4.0/), which permits
redistribution with attribution — hence it's committed here as-is.

It's a good stress test precisely because it's *not* a clean, single-column
synthetic doc: two-column layout, hyphenated line wraps, inline citations,
figures, and a real benchmark table.

## Files

- [`docling_example.pdf`](docling_example.pdf) — the input paper
- [`docling_example.jsonl`](docling_example.jsonl) — actual output from
  `vich parse examples/docling_example.pdf`, using `gpt-4.1-mini`
  (33 chunks from 8 pages, `batch_size=2`)
- [`chunk_visualization.html`](chunk_visualization.html) — open this in a
  browser: a document outline linking to every chunk, and each source page
  **with a numbered box + cropped image for every chunk vich found on it**,
  next to a card per chunk (see screenshot below)
- `generate_chunk_visualization.py` — the script that produced the
  visualization + `assets/`, kept so the example can be regenerated

Re-running `vich parse` won't reproduce this exact JSONL byte-for-byte —
chunk boundaries and content-type choices can vary slightly run to run —
but chunk *wording* should stay close to verbatim; see below.

## Reproducing

```bash
uv sync --extra dev

curl -sL "https://arxiv.org/pdf/2501.17887v1" -o examples/docling_example.pdf
uv run vich parse examples/docling_example.pdf --output-dir examples --overwrite
python examples/generate_chunk_visualization.py
open examples/chunk_visualization.html
```

## Two fixes this example surfaced

**1. Chunk text is grounded in the PDF's own text, not re-typed from the
image.** Earlier versions of this example showed the VLM paraphrasing
dense sentences — e.g. it once rendered the "Parser Backends" section as
*"...comparatively **easier** to parse,"* when the source actually says
*"...comparatively **inexpensive** to parse."* The chunker now also sends
the PDF's own extracted text (via PyMuPDF) alongside the page images, and
instructs the model to copy `chunk_text` verbatim from it — using the
images only for layout, reading order, headings, and table/figure
structure. This only grounds *wording*; the model still decides chunk
*boundaries* and `content_type` itself.

**2. A bigger batch risked the model dropping a paragraph outright.**
Grounding fixed wording, but a longer prompt (more page images *and* more
extracted text per call) turned out to have its own failure mode: on one
run with the old default (`batch_size=4`), the entire "1 Introduction"
section vanished from the output — not paraphrased, just absent from every
chunk, even though the text was right there in what was sent to the model.
Two changes address this:
- `batch_size` now defaults to 2 (smaller prompt per call), and re-running
  with it did include the Introduction section correctly.
- `vich.chunking.coverage.coverage_ratio()` checks each batch's chunks
  against the extracted text it was given and prints a warning if a batch
  looks like it dropped content — visibility instead of a silent gap, since
  there's no way to force an LLM not to occasionally do this.

## Document outline

`vich.outline` (a real library feature, not a docs-only script — see the
[root README](../README.md#outline)) assembles all 33 chunks' flat
`level_1/2/3_heading` labels into a tree:

```bash
uv run vich outline examples/docling_example.jsonl
```

```text
- Docling: An Efficient Open-Source Toolkit for AI-driven Document Conversion
  - Abstract (1 chunk)
  - Introduction (1 chunk)
    - Features (1 chunk)
  - State of the Art (2 chunks)
  - Design and Architecture (1 chunk)
    - Docling Document (2 chunks)
  - Parser Backends
    - Parser Backends (1 chunk)
    - PDF Backends (1 chunk)
    - Other Backends (1 chunk)
  ...
```

The visualization's "Document outline" section renders the same tree, with
each heading linking down to its chunk's card.

## What the visualization shows

Each source page is rendered on the left with a numbered, color-coded box
around every chunk found on it; the matching numbered card on the right
shows a cropped thumbnail of that same region, the chunk's 3-level heading
breadcrumb, body (or table, rendered from `table_markdown`), and extracted
keywords.

![Chunk visualization: page 1 of the Docling paper, with boxes around the abstract, the full introduction section, the feature list, and the start of "State of the Art" — no gaps between them](assets/docling_page_1.png)

Every paragraph on this page is now claimed by a box — including the
"1 Introduction" section (chunk 2), the one that went missing entirely in
an earlier run before the batch-size/coverage fix above.

> **Note:** `vich`'s chunk schema has no bounding-box field — the VLM
> reasons over the whole page image and returns text, not coordinates. The
> boxes/crops here are a docs-only convenience: `generate_chunk_visualization.py`
> estimates each one by matching the chunk's own text back onto the PDF's
> text layer, splitting into separate regions wherever the match crosses a
> column break or a large gap, and extending upward for a `figure` chunk
> so the box lands on the whole figure, not just its caption (the VLM has
> nothing to transcribe from a figure's own graphic, so only the caption
> text matches directly). That only works for text-based PDFs, and it's
> not part of what `vich parse` outputs. (The outline above *is* part of
> vich's actual output, not a docs convenience.)
>
> The search also isn't limited to a chunk's own declared `page_start` —
> **2 of this example's 33 chunks are labeled with the wrong page** by the
> VLM itself, so each chunk is matched against a small window of nearby
> pages and shown wherever it actually lands, with a note on the card when
> that differs from vich's own label. That's a real accuracy limitation of
> the current chunker worth knowing about if you depend on
> `page_start`/`page_end` for precise citations.
