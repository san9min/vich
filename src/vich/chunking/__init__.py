"""VLM-driven chunk extraction.

TODO(migration): port and generalize from mafio:
- mafio/data/utils/visual_chunking.py
    PROMPT_TEMPLATE, build_prompt, call_vlm_chunker, extract_json_object,
    make_embedding_text, normalize_chunk
- mafio/data/preprocess.py
    process_pdf / process_raw_pdfs batching + JSONL writing loop

Drop domain-specific bits when porting (DOCUMENT_ID_TRANSLATIONS,
SOURCE_URLS, and the Korean-banking-specific prompt wording) in favor of a
generic, configurable prompt and an optional source_url passthrough.
"""
