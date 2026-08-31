"""Raw VLM chunk -> `Chunk` normalization.

Ported from mafio/data/utils/visual_chunking.py (make_embedding_text,
normalize_chunk, to_chunk_document_id). The mafio version resolved
`chunk_document_id` through a hardcoded bank-document translation table
(DOCUMENT_ID_TRANSLATIONS); that table was domain-specific and is not
carried over. Callers who need stable, human-readable ids across languages
can pass their own `id_resolver`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from typing import Any

from vich.schema import Chunk, ChunkMetadata

IdResolver = Callable[[str, str], str]


def default_id_resolver(source: str, document_id: str) -> str:
    """Fallback chunk_document_id: an ASCII-only slug of `document_id`.

    Non-ASCII titles (e.g. Korean/Japanese/Chinese filenames) collapse to
    "document"; pass a custom `id_resolver` to `normalize_chunk` if you
    need meaningful ids for those instead.
    """
    del source  # available to custom resolvers, unused by the default one
    ascii_fallback = re.sub(r"[^a-z0-9]+", "_", document_id.lower()).strip("_")
    return ascii_fallback or "document"


def make_embedding_text(chunk: dict[str, Any], source: str) -> str:
    """Compose the text actually sent to the embedding model.

    Prepends heading hierarchy + keywords/entities to the chunk body so
    both sparse and dense retrieval reflect document structure, not just
    the raw chunk text.
    """
    level_1 = chunk.get("level_1_heading") or ""
    level_2 = chunk.get("level_2_heading") or ""
    level_3 = chunk.get("level_3_heading") or ""
    chunk_text = chunk.get("chunk_text") or ""
    keywords = chunk.get("keywords") or []
    entities = chunk.get("entities") or []

    return f"""source: {source}
title: {level_1}
section: {level_2}
topic: {level_3}
keywords: {", ".join(map(str, keywords))}
entities: {", ".join(map(str, entities))}

content:
{chunk_text}
""".strip()


def normalize_chunk(
    raw_chunk: dict[str, Any],
    document_id: str,
    source: str,
    source_url: str,
    page_start: int,
    page_end: int,
    idx: int,
    id_resolver: IdResolver = default_id_resolver,
) -> Chunk:
    """Turn one raw VLM chunk dict into a validated `Chunk`."""
    normalized_source = unicodedata.normalize("NFKC", source).strip()
    chunk_document_id = id_resolver(normalized_source, document_id)
    chunk_id = f"{chunk_document_id}_{idx}"

    fields = {
        "document_id": chunk_document_id,
        "source": source,
        "source_url": source_url,
        "page_start": raw_chunk.get("page_start") or page_start,
        "page_end": raw_chunk.get("page_end") or page_end,
        "level_1_heading": raw_chunk.get("level_1_heading"),
        "level_2_heading": raw_chunk.get("level_2_heading"),
        "level_3_heading": raw_chunk.get("level_3_heading"),
        "content_type": raw_chunk.get("content_type"),
        "continuation_status": raw_chunk.get("continuation_status"),
    }

    return Chunk(
        chunk_id=chunk_id,
        chunk_text=raw_chunk.get("chunk_text"),
        table_markdown=raw_chunk.get("table_markdown"),
        keywords=raw_chunk.get("keywords") or [],
        entities=raw_chunk.get("entities") or [],
        source_notes=raw_chunk.get("source_notes"),
        embedding_text=make_embedding_text(raw_chunk, source),
        metadata=ChunkMetadata(**fields),
        **fields,
    )
