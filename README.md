# ViCH: VLM-based Hierarchical Chunking for Structured Documents

Layout-aware PDF parsing and chunking for RAG pipelines, powered by a
vision-language model (VLM) instead of fixed-length text splitting.

> **Status: early scaffold.** The core parsing/chunking logic is being
> extracted and generalized from a private project
> ([mafio](https://github.com/san9min/mafio)) and is not implemented here
> yet. This README describes the intended shape of the project.

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

## Planned project structure

```text
vich/
├── src/vich/
│   ├── parsing/     # PDF -> page images (PyMuPDF-based rendering)
│   ├── chunking/     # VLM prompt + chunk extraction/normalization
│   ├── schema.py      # Chunk / output data models
│   └── cli.py         # `vich` command-line entrypoint
├── tests/
├── examples/           # Sample PDFs + expected output for docs
├── pyproject.toml
└── LICENSE (MIT)
```

## Install (once implemented)

```bash
uv sync
```

## Roadmap

- [ ] Port and generalize the VLM chunking pipeline (drop domain-specific
      bank/document data, keep the layout-aware chunking approach)
- [ ] Pluggable VLM backend (OpenAI-compatible today; others later)
- [ ] `vich parse <pdf>` CLI producing JSONL chunks
- [ ] Docs + example PDF walkthrough
- [ ] Tests

## License

[MIT](LICENSE)
