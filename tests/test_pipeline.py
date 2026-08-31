import json
from pathlib import Path

from vich import pipeline


def test_process_pdf_assigns_dense_sequential_chunk_ids(tmp_path, monkeypatch):
    """Regression test: idx used to be recomputed as len(all_chunks) + local_idx
    *inside* the append loop, so it drifted from a dense 0..N-1 sequence the
    moment a batch produced more than one chunk (0, 2, 4, ... instead of
    0, 1, 2, ...), and batches after the first started from the wrong base
    entirely. chunk_id must stay dense and sequential across batches."""

    monkeypatch.setattr(pipeline, "count_pages", lambda pdf_path: 8)
    monkeypatch.setattr(pipeline, "render_pdf_pages_to_base64", lambda **kwargs: [])

    # Two batches (batch_size=4, 8 pages) with 3 and 2 chunks respectively.
    batch_results = iter(
        [
            {"chunks": [{"chunk_text": "a"}, {"chunk_text": "b"}, {"chunk_text": "c"}]},
            {"chunks": [{"chunk_text": "d"}, {"chunk_text": "e"}]},
        ]
    )
    monkeypatch.setattr(pipeline, "call_vlm_chunker", lambda **kwargs: next(batch_results))

    output_path = pipeline.process_pdf(
        client=object(),
        pdf_path=Path("document.pdf"),
        output_dir=tmp_path,
        model="test-model",
        batch_size=4,
    )

    lines = output_path.read_text(encoding="utf-8").splitlines()
    chunk_ids = [json.loads(line)["chunk_id"] for line in lines]

    assert chunk_ids == [f"document_{i}" for i in range(5)]
