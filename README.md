# ViCH: VLM-based Hierarchical Chunking for Structured Documents

Layout-aware PDF parsing and chunking for RAG pipelines, powered by a
vision-language model (VLM) instead of fixed-length text splitting.

> **Status: early, functional.** The core parsing/chunking logic has been
> extracted and generalized from a private project
> ([mafio](https://github.com/san9min/mafio)). It works end-to-end against
> the OpenAI Responses API but is not yet published or widely tested.

## Why

Fixed-length or heading-regex text splitters break down on real-world
structured PDFs — tables, boxed notes, footnotes, multi-column layouts, and
section hierarchies that are only legible from the page's visual layout.
ViCH instead renders each page as an image and asks a VLM to produce
**layout-aware semantic chunks** (paragraphs, tables, boxed sections, figures)
directly from the page, preserving:

- A 3-level heading hierarchy (`level_1` / `level_2` / `level_3`) per chunk
- Page-range metadata and continuation status across page/batch boundaries
- Table structure as markdown, not flattened text
- Keywords/entities per chunk for hybrid (sparse + dense) retrieval

Each chunk's heading labels are flat (`level_1/2/3_heading` strings); `vich`
separately assembles them into a document-wide heading tree — see
[Outline](#outline) below.

The VLM also gets the PDF's own extracted text (via PyMuPDF) alongside the
page images, and is told to copy `chunk_text` verbatim from it — the
images are for layout/structure decisions, not re-transcribing text the
model already has exactly. Without this, dense sentences drift into
paraphrasing (an LLM "reading" an image tends to summarize, not
transcribe); see [`examples/README.md`](examples/README.md) for a
before/after. That fix has its own failure mode, though: a longer prompt
(more images and more extracted text per call) makes it more likely the
model drops a paragraph outright instead of merely paraphrasing it —
observed in practice on the example paper, from a batch whose *overall*
word coverage still looked fine. A warning alone doesn't fix a dropped
paragraph, so `vich.chunking.recovery` checks coverage per paragraph-ish
block instead (PyMuPDF's own layout segmentation) and inserts a fallback
chunk built from any block's verbatim text that the VLM's own chunks don't
cover — see [`examples/README.md`](examples/README.md) for this caught
live on a real run.

Chunking itself is a **two-stage pipeline** — see [Two-stage design](#two-stage-design)
below for why: cramming "invent this document's heading hierarchy" and
"transcribe this batch's content" into the same per-batch call was itself
a source of inconsistency (the same section coming back worded
differently across batches), not just a prompt-size problem.

## Two-stage design

Earlier versions asked one VLM call to *simultaneously* invent heading
hierarchy, transcribe body text verbatim, classify content_type, and
extract keywords, for a growing batch of pages — and re-deriving the
hierarchy fresh in every batch meant the same section could come back
worded slightly differently between batches (observed in practice:
"Parser Backends" nested one way in one run, flattened differently in
another), which broke grouping chunks under it after the fact.

`process_pdf` now runs two stages:

1. **Once per document**, `vich.chunking.outline_extraction.extract_document_outline`
   reads every page (images + extracted text) and returns *only* the
   heading structure — no content, no chunk_text, a small output — so
   nothing about it is likely to get dropped the way a batch's content
   sometimes does.
2. **Per batch**, `vich.chunking.client.call_vlm_chunker` gets that outline
   as context and *classifies* each chunk's heading against it (copy the
   exact wording of the matching entry) instead of inventing one. This is
   a much easier, more consistent task than re-deriving hierarchy from
   scratch — and it means a chunk whose section spans a page or batch
   break doesn't need to be merged into one physical chunk_text to "belong
   together": as long as its heading matches an earlier chunk's exactly,
   `vich.outline.build_outline` groups them correctly after the fact, even
   across completely different batches.

Pass `--outline-model` (CLI) / `outline_model=` (library) to use a
different — e.g. stronger — model for stage 1 than stage 2; getting the
outline right matters more than any single chunking batch, since every
batch depends on it. Both default to the same model.

This isn't free of failure modes either: if stage 1 misses a real
section (an unnumbered "Abstract" before "1 Introduction" was missed on
an early attempt), stage 2 can either invent a heading for that content
per rule 2's fallback, or — observed once — fold it wholesale into an
adjacent numbered section instead of giving it its own chunk. The prompt
now calls out common unnumbered front-matter sections explicitly and
states that heading-matching never reduces how many chunks a page gets,
but stage 1 is still a single VLM call making a judgment, not a
guarantee.

## Project structure

```text
vich/
├── src/vich/
│   ├── parsing/                    # PDF -> page images/text (PyMuPDF-based)
│   ├── chunking/
│   │   ├── outline_extraction.py    # Stage 1: whole-document heading structure
│   │   ├── prompt.py                 # Stage 2: per-batch chunking prompt
│   │   ├── client.py                 # VLM call + JSON extraction
│   │   ├── normalize.py              # Raw VLM chunk -> Chunk
│   │   ├── coverage.py               # Word-overlap primitives
│   │   └── recovery.py               # Detect + repair content a batch dropped
│   ├── schema.py                    # Chunk / output data models (pydantic)
│   ├── outline.py                    # Assemble *produced* chunks' headings into a tree
│   ├── pipeline.py                   # Two-stage orchestration -> JSONL
│   └── cli.py                        # `vich` command-line entrypoint
├── tests/
├── examples/                          # Sample PDFs + expected output for docs
├── pyproject.toml
└── LICENSE (MIT)
```

## Install

```bash
uv sync
cp .env.example .env  # set OPENAI_API_KEY and VICH_VLM_MODEL
```

## Usage

```bash
# Single PDF
uv run vich parse path/to/document.pdf

# Every PDF in a directory
uv run vich parse path/to/pdf_dir --output-dir data/processed
```

Or as a library:

```python
from openai import OpenAI
from vich import process_pdf

process_pdf(
    client=OpenAI(),
    pdf_path=Path("document.pdf"),
    model="gpt-4.1-mini",
)
```

Each chunk (see `vich.schema.Chunk`) carries a 3-level heading hierarchy,
page range, content type, table markdown (when applicable), keywords,
entities, and a precomposed `embedding_text` ready for a vector store.

## Outline

Two different things share the name "outline" in this codebase, deliberately
related but not the same:

- `vich.chunking.outline_extraction` (stage 1 above) runs *before*
  chunking, from the page images/text, to establish the heading structure
  chunking will use.
- `vich.outline` runs *after* chunking, for free (no VLM call), over
  already-produced chunks' flat `level_1/2/3_heading` labels — it's what
  turns "every chunk under 'Ecosystem' happens to say 'Ecosystem'
  identically" into an actual tree you can navigate or print:

```bash
uv run vich outline examples/docling_example.jsonl
```

```text
- Docling: An Efficient Open-Source Toolkit for AI-driven Document Conversion
  - Abstract (1 chunk)
  - 1 Introduction (2 chunks)
  - 2 State of the Art (2 chunks)
  - 3 Design and Architecture (1 chunk)
    - 3.1 Docling Document (1 chunk)
    - 3.2 Parser Backends (3 chunks)
    - 3.3 Pipelines (1 chunk)
  ...
```

Or as a library: `vich.build_outline(chunks)` returns a tree of
`OutlineNode` (`title`, `level`, `children`, `chunk_ids`); `render_outline_markdown(...)`
renders it as above.

## Content recovery

`process_pdf` automatically checks each batch's chunks against
`vich.parsing.extract_page_blocks` (the PDF's own paragraph-ish text
blocks) and inserts a fallback chunk for any block that's substantial
(15+ significant words) and barely covered (<30% word overlap) by what
the VLM actually produced — `content_type: "paragraph"`,
`source_notes` marked `"Auto-recovered: ..."`, heading labels inherited
from the chunk right before it. This runs on every `vich parse` call, no
flag needed, and prints `Recovered N block(s) ...` when it fires. It's
mechanical, not semantic — a recovered chunk is exact source text, not a
VLM's curated chunk — but it means nothing substantial silently
disappears just because the model's own chunking missed it.

## Example

See [`examples/`](examples/) for a worked example: a real academic PDF, the
actual JSONL chunks vich produces from it, and a
[chunk visualization page](examples/chunk_visualization.html) showing each
source page with a box (and cropped image) for every chunk, colored by
which section it belongs to (not by `content_type`) so the hierarchy is
visible directly on the page, plus the document outline linking down to
each one.

## Known limitations

- **`page_start`/`page_end` aren't fully reliable.** They come from the
  VLM's own self-reported labels for each chunk, and on the example paper
  in [`examples/`](examples/) a couple of chunks are off by a page. If you
  need precise page citations, verify them rather than trusting them
  outright — see the note in [`examples/README.md`](examples/README.md)
  for how this was found. (Text-grounding chunk_text against the PDF's
  extracted text fixed *wording* fidelity; it doesn't fix page attribution,
  which is a separate self-reported field.)
- **The model can drop a paragraph outright, not just paraphrase it** —
  there's no way to force an LLM not to do this. `vich.chunking.recovery`
  (see [Content recovery](#content-recovery)) catches and repairs this at
  the paragraph level rather than just warning about it, but it's a
  mechanical safety net, not a guarantee stronger than its own thresholds —
  a dropped fragment under ~15 significant words, or one an unrelated
  chunk happens to share a lot of vocabulary with, could still slip
  through.
- **Stage 1 (outline extraction) can miss a real section.** Every chunk's
  heading depends on it, so a section it misses either gets folded into an
  adjacent one or gets an ad-hoc heading from stage 2's fallback — both
  observed in testing (an unnumbered "Abstract" before "1 Introduction"
  was initially missed and its content folded into "1 Introduction"
  wholesale; the prompt now calls out unnumbered front-matter sections
  explicitly, but stage 1 is still a single VLM call's judgment, not a
  guarantee). Sanity-check the outline on a new document type with
  `vich outline` before trusting the heading labels at scale.
- **Chunk boundaries and `content_type` choices vary between runs** on the
  same PDF, since they're still an LLM's judgment call, not a deterministic
  rule. Re-running `vich parse` on the same file won't reproduce byte-for-byte
  identical output. (Heading *wording* is the exception — that's now
  anchored to stage 1's outline and stays consistent within a run, and
  usually across re-runs too since it's the same document structure.)

## Roadmap

- [x] Port and generalize the VLM chunking pipeline (drop domain-specific
      bank/document data, keep the layout-aware chunking approach)
- [x] Docs + example PDF walkthrough
- [x] Document outline (`vich.outline`)
- [x] Ground chunk_text in the PDF's extracted text (reduce paraphrasing)
- [x] Detect and recover dropped content (`vich.chunking.recovery`)
- [x] Two-stage pipeline: whole-document outline, then per-batch chunking
      against it (`vich.chunking.outline_extraction`)
- [ ] Pluggable VLM backend (OpenAI-compatible today; others later)
- [ ] More reliable per-chunk page attribution
- [ ] Publish to PyPI

## License

[MIT](LICENSE)
