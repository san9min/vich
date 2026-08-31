"""ViCH: VLM-based Hierarchical Chunking for Structured Documents.

Layout-aware PDF parsing and chunking for RAG pipelines.
"""

from vich.pipeline import process_documents, process_pdf
from vich.schema import Chunk, ChunkMetadata, HeadingHierarchy

__version__ = "0.1.0"

__all__ = [
    "Chunk",
    "ChunkMetadata",
    "HeadingHierarchy",
    "__version__",
    "process_documents",
    "process_pdf",
]
