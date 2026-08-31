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
    monkeypatch.setattr(pipeline, "extract_page_text", lambda **kwargs: "")

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


def test_process_pdf_passes_extracted_page_text_to_the_vlm_call(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "count_pages", lambda pdf_path: 1)
    monkeypatch.setattr(pipeline, "render_pdf_pages_to_base64", lambda **kwargs: [])
    monkeypatch.setattr(
        pipeline, "extract_page_text", lambda **kwargs: "--- page 1 ---\nVerbatim source text."
    )

    seen_texts = []

    def fake_call_vlm_chunker(**kwargs):
        seen_texts.append(kwargs["extracted_page_text"])
        return {"chunks": []}

    monkeypatch.setattr(pipeline, "call_vlm_chunker", fake_call_vlm_chunker)

    pipeline.process_pdf(
        client=object(),
        pdf_path=Path("document.pdf"),
        output_dir=tmp_path,
        model="test-model",
    )

    assert seen_texts == ["--- page 1 ---\nVerbatim source text."]


def test_process_pdf_warns_when_a_batch_drops_content(tmp_path, monkeypatch, capsys):
    """The VLM can simply omit a paragraph from its output rather than
    paraphrasing it (this is what actually happened on the example PDF: an
    entire introduction section vanished from one run). There's no way to
    force it not to, so a batch with low word-overlap against the extracted
    text should at least print a warning instead of failing silently."""
    monkeypatch.setattr(pipeline, "count_pages", lambda pdf_path: 1)
    monkeypatch.setattr(pipeline, "render_pdf_pages_to_base64", lambda **kwargs: [])
    monkeypatch.setattr(
        pipeline,
        "extract_page_text",
        lambda **kwargs: (
            "Converting documents back into a unified machine-processable format "
            "has been a major challenge for decades due to variability in formats."
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "call_vlm_chunker",
        lambda **kwargs: {"chunks": [{"chunk_text": "Some unrelated short chunk."}]},
    )

    pipeline.process_pdf(
        client=object(), pdf_path=Path("document.pdf"), output_dir=tmp_path, model="test-model"
    )

    assert "may be missing content" in capsys.readouterr().out


def test_process_pdf_does_not_warn_when_coverage_is_good(tmp_path, monkeypatch, capsys):
    text = "Docling releases two highly capable AI models for layout analysis."
    monkeypatch.setattr(pipeline, "count_pages", lambda pdf_path: 1)
    monkeypatch.setattr(pipeline, "render_pdf_pages_to_base64", lambda **kwargs: [])
    monkeypatch.setattr(pipeline, "extract_page_text", lambda **kwargs: text)
    monkeypatch.setattr(pipeline, "call_vlm_chunker", lambda **kwargs: {"chunks": [{"chunk_text": text}]})

    pipeline.process_pdf(
        client=object(), pdf_path=Path("document.pdf"), output_dir=tmp_path, model="test-model"
    )

    assert "may be missing content" not in capsys.readouterr().out
