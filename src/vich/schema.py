"""Chunk output data models.

TODO(migration): formalize the JSONL chunk schema currently documented as a
comment in mafio/data/preprocess.py into pydantic models here, e.g.:

    class ChunkMetadata(BaseModel): ...
    class Chunk(BaseModel): ...

Fields to carry over: chunk_id, document_id, source, source_url,
page_start, page_end, level_1/2/3_heading, content_type,
continuation_status, chunk_text, table_markdown, keywords, entities,
source_notes, embedding_text, metadata.
"""
