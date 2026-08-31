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
**layout-aware semantic chunks** (paragraphs, tables, lists, boxed sections)
directly from the page, preserving:

- A 3-level heading hierarchy (`level_1` / `level_2` / `level_3`) per chunk
- Page-range metadata and continuation status across page/batch boundaries
- Table structure as markdown, not flattened text
- Keywords/entities per chunk for hybrid (sparse + dense) retrieval

## Project structure

```text
vich/
├── src/vich/
│   ├── parsing/         # PDF -> page images (PyMuPDF-based rendering)
│   ├── chunking/        # VLM prompt + chunk extraction/normalization
│   ├── schema.py        # Chunk / output data models (pydantic)
│   ├── pipeline.py       # Batch PDF -> JSONL orchestration
│   └── cli.py            # `vich` command-line entrypoint
├── tests/
├── examples/              # Sample PDFs + expected output for docs
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

## Roadmap

- [x] Port and generalize the VLM chunking pipeline (drop domain-specific
      bank/document data, keep the layout-aware chunking approach)
- [ ] Pluggable VLM backend (OpenAI-compatible today; others later)
- [ ] Docs + example PDF walkthrough
- [ ] Publish to PyPI

## License

[MIT](LICENSE)
