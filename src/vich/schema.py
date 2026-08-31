"""Chunk output data models.

Formalizes the JSONL chunk schema that lived as a comment in
mafio/data/preprocess.py into pydantic models.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ContentType = Literal[
    "paragraph", "table", "boxed_section", "list", "footnote", "figure", "mixed"
]
ContinuationStatus = Literal["new", "continues", "partial"]


class HeadingHierarchy(BaseModel):
    """Running heading state carried across page batches for continuity."""

    level_1: str | None = None
    level_2_candidates: list[str] = Field(default_factory=list)
    level_3_candidates: list[str] = Field(default_factory=list)


class ChunkMetadata(BaseModel):
    """The subset of a chunk's fields meant for vector-store metadata."""

    document_id: str
    source: str
    source_url: str = ""
    page_start: int
    page_end: int
    level_1_heading: str | None = None
    level_2_heading: str | None = None
    level_3_heading: str | None = None
    content_type: ContentType | None = None
    continuation_status: ContinuationStatus | None = None


class Chunk(BaseModel):
    """A single retrieval-ready chunk produced by the VLM chunker."""

    chunk_id: str
    document_id: str
    source: str
    source_url: str = ""
    page_start: int
    page_end: int
    level_1_heading: str | None = None
    level_2_heading: str | None = None
    level_3_heading: str | None = None
    content_type: ContentType | None = None
    continuation_status: ContinuationStatus | None = None
    chunk_text: str | None = None
    table_markdown: str | None = None
    keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    source_notes: str | None = None
    embedding_text: str = ""
    metadata: ChunkMetadata

    def to_jsonl_line(self) -> str:
        return self.model_dump_json(exclude_none=False)


class BatchResult(BaseModel):
    """Raw VLM output for one page batch, before chunk normalization."""

    document_id: str = ""
    source: str = ""
    page_range: str = ""
    batch_summary: str = ""
    heading_hierarchy: HeadingHierarchy = Field(default_factory=HeadingHierarchy)
    chunks: list[dict] = Field(default_factory=list)
