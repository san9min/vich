"""ViCH: VLM-based Hierarchical Chunking for Structured Documents.

Layout-aware PDF parsing and chunking for RAG pipelines.
"""

from vich.outline import OutlineNode, build_outline, render_outline_markdown
from vich.pipeline import process_documents, process_pdf
from vich.schema import Chunk, ChunkMetadata, HeadingHierarchy, load_chunks

__version__ = "0.1.0"

__all__ = [
    "Chunk",
    "ChunkMetadata",
    "HeadingHierarchy",
    "OutlineNode",
    "__version__",
    "build_outline",
    "load_chunks",
    "process_documents",
    "process_pdf",
    "render_outline_markdown",
]
