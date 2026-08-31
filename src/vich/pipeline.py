"""End-to-end PDF -> JSONL chunk pipeline.

Ported from mafio/data/preprocess.py (process_pdf, process_raw_pdfs),
generalized to drop the hardcoded bank-document `SOURCE_URLS` lookup: pass
`source_url` explicitly per document instead.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI
from tqdm import tqdm

from vich.chunking.client import call_vlm_chunker
from vich.chunking.normalize import IdResolver, default_id_resolver, normalize_chunk
from vich.parsing.pdf_renderer import count_pages, render_pdf_pages_to_base64, safe_stem
from vich.schema import Chunk

DEFAULT_OUTPUT_DIR = Path("data/processed")


def process_pdf(
    client: OpenAI,
    pdf_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    model: str | None = None,
    batch_size: int = 4,
    zoom: float = 2.0,
    overwrite: bool = False,
    source_url: str = "",
    id_resolver: IdResolver = default_id_resolver,
) -> Path:
    """Chunk one PDF and write it as `<output_dir>/<document_id>.jsonl`.

    Pages are processed in batches of `batch_size`; each batch is rendered
    to images, sent to the VLM chunker, and the resulting chunks are
    normalized and appended. Heading hierarchy and a short summary carry
    over between batches so chunking stays consistent across page breaks.
    """
    resolved_model = model or os.getenv("VICH_VLM_MODEL")
    if not resolved_model:
        raise ValueError("Missing model. Pass `model=` or set VICH_VLM_MODEL.")

    document_id = safe_stem(pdf_path)
    source = pdf_path.stem
    output_path = output_dir / f"{document_id}.jsonl"

    if output_path.exists() and not overwrite:
        print(f"Skip existing: {output_path}")
        return output_path

    total_pages = count_pages(pdf_path)

    previous_batch_summary = ""
    previous_last_chunk = ""
    previous_heading_hierarchy: dict[str, Any] = {}
    all_chunks: list[Chunk] = []

    for page_start in tqdm(range(1, total_pages + 1, batch_size), desc=f"Processing {source}"):
        page_end = min(page_start + batch_size - 1, total_pages)

        page_images = render_pdf_pages_to_base64(
            pdf_path=pdf_path,
            page_start=page_start,
            page_end=page_end,
            zoom=zoom,
        )

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
            previous_heading_hierarchy=previous_heading_hierarchy,
        )

        raw_chunks = batch_result.get("chunks") or []

        for local_idx, raw_chunk in enumerate(raw_chunks):
            chunk = normalize_chunk(
                raw_chunk=raw_chunk,
                document_id=document_id,
                source=source,
                source_url=source_url,
                page_start=page_start,
                page_end=page_end,
                idx=len(all_chunks) + local_idx,
                id_resolver=id_resolver,
            )
            all_chunks.append(chunk)

        previous_batch_summary = batch_result.get("batch_summary") or previous_batch_summary
        previous_heading_hierarchy = (
            batch_result.get("heading_hierarchy") or previous_heading_hierarchy
        )

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
    batch_size: int = 4,
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
