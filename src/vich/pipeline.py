"""End-to-end PDF -> JSONL chunk pipeline.

Ported from mafio/data/preprocess.py (process_pdf, process_raw_pdfs),
generalized to drop the hardcoded bank-document `SOURCE_URLS` lookup: pass
`source_url` explicitly per document instead.

Two-stage design: `process_pdf` first calls
`vich.chunking.outline_extraction.extract_document_outline` once for the
whole document, then runs the batch-by-batch chunking loop as before, with
each batch's prompt now anchored to that outline instead of inventing
heading hierarchy fresh per batch. See `vich.chunking.prompt`'s module
docstring for why: re-deriving hierarchy independently in every batch let
the same section come back worded differently across batches, which broke
grouping chunks under it after the fact (`vich.outline.build_outline`) --
that's now handled by classification against an already-settled list
instead.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from openai import OpenAI
from tqdm import tqdm

from vich.chunking.client import call_vlm_chunker
from vich.chunking.normalize import IdResolver, default_id_resolver, normalize_chunk
from vich.chunking.outline_extraction import extract_document_outline, render_known_outline_text
from vich.chunking.recovery import find_missed_blocks
from vich.parsing.pdf_renderer import (
    count_pages,
    extract_page_blocks,
    extract_page_text,
    render_pdf_pages_to_base64,
    safe_stem,
)
from vich.schema import Chunk

DEFAULT_OUTPUT_DIR = Path("data/processed")


def process_pdf(
    client: OpenAI,
    pdf_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    model: str | None = None,
    outline_model: str | None = None,
    batch_size: int = 2,
    zoom: float = 2.0,
    overwrite: bool = False,
    source_url: str = "",
    id_resolver: IdResolver = default_id_resolver,
) -> Path:
    """Chunk one PDF and write it as `<output_dir>/<document_id>.jsonl`.

    Stage 1 (once): the whole document's pages + extracted text go to
    `extract_document_outline` in a single call, which returns only a
    heading structure (small output), not content -- establishing a
    canonical, exact-wording list of headings before any chunking happens.
    `outline_model` lets this stage use a different (e.g. stronger) model
    than the per-batch chunking in stage 2; defaults to `model`.

    Stage 2 (per batch): pages are processed in batches of `batch_size`,
    each rendered to images and sent to the VLM chunker alongside that
    page range's own extracted text and the stage-1 outline, and the
    resulting chunks are normalized and appended. A short summary still
    carries forward between batches for local continuity (e.g. judging
    continuation_status), but cross-batch *heading* consistency now comes
    from the shared stage-1 outline rather than a per-batch carry-forward.

    `batch_size` defaults small (2) because a bigger batch means a longer
    prompt (more page images plus more extracted text), and a longer
    prompt makes it more likely the model drops a paragraph outright
    instead of merely paraphrasing it -- observed in practice on a 4-page
    batch of a dense academic paper. Raise it for faster/cheaper runs on
    sparser documents; any paragraph a batch that size still drops gets
    caught and recovered regardless (see `vich.chunking.recovery`).
    """
    resolved_model = model or os.getenv("VICH_VLM_MODEL")
    if not resolved_model:
        raise ValueError("Missing model. Pass `model=` or set VICH_VLM_MODEL.")
    resolved_outline_model = outline_model or resolved_model

    document_id = safe_stem(pdf_path)
    source = pdf_path.stem
    output_path = output_dir / f"{document_id}.jsonl"

    if output_path.exists() and not overwrite:
        print(f"Skip existing: {output_path}")
        return output_path

    total_pages = count_pages(pdf_path)

    print(f"Extracting document outline for {source}...")
    outline_page_images = render_pdf_pages_to_base64(
        pdf_path=pdf_path, page_start=1, page_end=total_pages, zoom=zoom
    )
    outline_source_text = extract_page_text(pdf_path=pdf_path, page_start=1, page_end=total_pages)
    raw_outline = extract_document_outline(
        client=client,
        model=resolved_outline_model,
        document_id=document_id,
        source=source,
        page_images=outline_page_images,
        extracted_text=outline_source_text,
    )
    known_outline = render_known_outline_text(raw_outline)
    print(known_outline or "(no outline extracted)")

    previous_batch_summary = ""
    previous_last_chunk = ""
    all_chunks: list[Chunk] = []

    for page_start in tqdm(range(1, total_pages + 1, batch_size), desc=f"Processing {source}"):
        page_end = min(page_start + batch_size - 1, total_pages)

        page_images = render_pdf_pages_to_base64(
            pdf_path=pdf_path,
            page_start=page_start,
            page_end=page_end,
            zoom=zoom,
        )
        page_text = extract_page_text(pdf_path=pdf_path, page_start=page_start, page_end=page_end)

        batch_result = call_vlm_chunker(
            client=client,
            model=resolved_model,
            document_id=document_id,
            source=source,
            page_start=page_start,
            page_end=page_end,
            page_images=page_images,
            previous_batch_summary=previous_batch_summary,
            previous_last_chunk=previous_last_chunk,
            extracted_page_text=page_text,
            known_outline=known_outline,
        )

        raw_chunks = batch_result.get("chunks") or []
        base_idx = len(all_chunks)  # fixed offset: don't re-read len(all_chunks) as it grows below

        for local_idx, raw_chunk in enumerate(raw_chunks):
            chunk = normalize_chunk(
                raw_chunk=raw_chunk,
                document_id=document_id,
                source=source,
                source_url=source_url,
                page_start=page_start,
                page_end=page_end,
                idx=base_idx + local_idx,
                id_resolver=id_resolver,
            )
            all_chunks.append(chunk)

        batch_chunks = all_chunks[base_idx:]
        batch_chunk_texts = [c.chunk_text or "" for c in batch_chunks] + [
            c.table_markdown or "" for c in batch_chunks
        ]
        page_blocks = extract_page_blocks(pdf_path=pdf_path, page_start=page_start, page_end=page_end)
        missed_blocks = find_missed_blocks(page_blocks, batch_chunk_texts)

        for missed in missed_blocks:
            last_chunk = all_chunks[-1] if all_chunks else None
            recovered = normalize_chunk(
                raw_chunk={
                    "chunk_text": missed["text"],
                    "content_type": "paragraph",
                    "continuation_status": "partial",
                    "level_1_heading": last_chunk.level_1_heading if last_chunk else None,
                    "level_2_heading": last_chunk.level_2_heading if last_chunk else None,
                    "source_notes": (
                        "Auto-recovered: present in the source but omitted from the "
                        "VLM's own chunking output for this batch."
                    ),
                },
                document_id=document_id,
                source=source,
                source_url=source_url,
                page_start=missed["page_num"],
                page_end=missed["page_num"],
                idx=len(all_chunks),
                id_resolver=id_resolver,
            )
            all_chunks.append(recovered)

        if missed_blocks:
            print(
                f"Recovered {len(missed_blocks)} block(s) the VLM omitted from pages "
                f"{page_start}-{page_end} of {source} (see source_notes)"
            )

        previous_batch_summary = batch_result.get("batch_summary") or previous_batch_summary

        if raw_chunks:
            previous_last_chunk = json.dumps(raw_chunks[-1], ensure_ascii=False)

    output_dir.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for chunk in all_chunks:
            handle.write(chunk.to_jsonl_line() + "\n")

    print(f"Saved {len(all_chunks)} chunks: {output_path}")
    return output_path


def process_documents(
    raw_dir: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    model: str | None = None,
    outline_model: str | None = None,
    batch_size: int = 2,
    zoom: float = 2.0,
    overwrite: bool = False,
    source_urls: dict[str, str] | None = None,
    id_resolver: IdResolver = default_id_resolver,
) -> list[Path]:
    """Chunk every PDF in `raw_dir`.

    `source_urls` optionally maps a PDF's slugified stem (see
    `vich.parsing.safe_stem`) to a URL to attach as `source_url`; PDFs not
    in the mapping default to an empty source_url. Per-file failures are
    logged and skipped rather than aborting the whole run.
    """
    resolved_model = model or os.getenv("VICH_VLM_MODEL")
    if not resolved_model:
        raise ValueError("Missing model. Pass `model=` or set VICH_VLM_MODEL.")

    if not raw_dir.exists():
        raise FileNotFoundError(f"raw_dir not found: {raw_dir}")

    pdf_files = sorted(raw_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {raw_dir}")
        return []

    client = OpenAI()
    source_urls = source_urls or {}
    output_paths: list[Path] = []

    for pdf_path in pdf_files:
        try:
            output_paths.append(
                process_pdf(
                    client=client,
                    pdf_path=pdf_path,
                    output_dir=output_dir,
                    model=resolved_model,
                    outline_model=outline_model,
                    batch_size=batch_size,
                    zoom=zoom,
                    overwrite=overwrite,
                    source_url=source_urls.get(safe_stem(pdf_path), ""),
                    id_resolver=id_resolver,
                )
            )
        except Exception as exc:  # noqa: BLE001 - one bad PDF shouldn't stop the batch
            print(f"Failed: {pdf_path.name}")
            print(f"Error: {exc!r}")

    return output_paths
