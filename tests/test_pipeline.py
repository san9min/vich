import json
from pathlib import Path

from vich import pipeline


def _stub_outline(**kwargs):
    return {}


def test_process_pdf_assigns_dense_sequential_chunk_ids(tmp_path, monkeypatch):
    """Regression test: idx used to be recomputed as len(all_chunks) + local_idx
    *inside* the append loop, so it drifted from a dense 0..N-1 sequence the
    moment a batch produced more than one chunk (0, 2, 4, ... instead of
    0, 1, 2, ...), and batches after the first started from the wrong base
    entirely. chunk_id must stay dense and sequential across batches."""

    monkeypatch.setattr(pipeline, "count_pages", lambda pdf_path: 8)
    monkeypatch.setattr(pipeline, "render_pdf_pages_to_base64", lambda **kwargs: [])
    monkeypatch.setattr(pipeline, "extract_page_text", lambda **kwargs: "")
    monkeypatch.setattr(pipeline, "extract_page_blocks", lambda **kwargs: [])
    monkeypatch.setattr(pipeline, "extract_document_outline", _stub_outline)

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
    monkeypatch.setattr(pipeline, "extract_page_blocks", lambda **kwargs: [])
    monkeypatch.setattr(pipeline, "extract_document_outline", _stub_outline)

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


def test_process_pdf_extracts_a_whole_document_outline_once_and_passes_it_to_every_batch(
    tmp_path, monkeypatch
):
    """Stage 1 (outline) should cover the whole document in a single call
    (page 1 through the last page, not just one batch's range), and its
    rendered text should reach every stage-2 batch call as known_outline."""
    monkeypatch.setattr(pipeline, "count_pages", lambda pdf_path: 4)
    monkeypatch.setattr(pipeline, "render_pdf_pages_to_base64", lambda **kwargs: [])
    monkeypatch.setattr(pipeline, "extract_page_text", lambda **kwargs: "")
    monkeypatch.setattr(pipeline, "extract_page_blocks", lambda **kwargs: [])

    outline_calls = []

    def fake_extract_document_outline(**kwargs):
        outline_calls.append(kwargs)
        return {"level_1": "Doc Title", "sections": [{"level_2": "Intro", "first_page": 1, "subsections": []}]}

    monkeypatch.setattr(pipeline, "extract_document_outline", fake_extract_document_outline)

    seen_outlines = []

    def fake_call_vlm_chunker(**kwargs):
        seen_outlines.append(kwargs["known_outline"])
        return {"chunks": []}

    monkeypatch.setattr(pipeline, "call_vlm_chunker", fake_call_vlm_chunker)

    pipeline.process_pdf(
        client=object(),
        pdf_path=Path("document.pdf"),
        output_dir=tmp_path,
        model="test-model",
        batch_size=2,
    )

    assert len(outline_calls) == 1  # once per document, not once per batch
    # Two batches (batch_size=2, 4 pages), each seeing the same rendered outline.
    assert seen_outlines == ["- Doc Title\n  - Intro"] * 2


def test_process_pdf_can_use_a_different_model_for_the_outline_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "count_pages", lambda pdf_path: 1)
    monkeypatch.setattr(pipeline, "render_pdf_pages_to_base64", lambda **kwargs: [])
    monkeypatch.setattr(pipeline, "extract_page_text", lambda **kwargs: "")
    monkeypatch.setattr(pipeline, "extract_page_blocks", lambda **kwargs: [])
    monkeypatch.setattr(pipeline, "call_vlm_chunker", lambda **kwargs: {"chunks": []})

    seen_models = []
    monkeypatch.setattr(
        pipeline,
        "extract_document_outline",
        lambda **kwargs: seen_models.append(kwargs["model"]) or {},
    )

    pipeline.process_pdf(
        client=object(),
        pdf_path=Path("document.pdf"),
        output_dir=tmp_path,
        model="cheap-model",
        outline_model="strong-model",
    )

    assert seen_models == ["strong-model"]


def test_process_pdf_recovers_a_block_the_vlm_dropped(tmp_path, monkeypatch, capsys):
    """The VLM can simply omit a paragraph from its output rather than
    paraphrasing it (this is what actually happened on the example PDF: an
    entire introduction section vanished from one run, from a batch whose
    *overall* word coverage still looked fine). There's no way to force an
    LLM not to do this, so a dropped-but-substantial block should end up in
    the output anyway, as its own recovered chunk."""
    monkeypatch.setattr(pipeline, "count_pages", lambda pdf_path: 1)
    monkeypatch.setattr(pipeline, "render_pdf_pages_to_base64", lambda **kwargs: [])
    monkeypatch.setattr(pipeline, "extract_page_text", lambda **kwargs: "")
    monkeypatch.setattr(pipeline, "extract_document_outline", _stub_outline)

    dropped_text = (
        "Converting documents back into a unified machine-processable format "
        "has been a major challenge for decades due to variability in formats "
        "and weak standardization across the industry as a whole."
    )
    monkeypatch.setattr(
        pipeline,
        "extract_page_blocks",
        lambda **kwargs: [{"page_num": 1, "text": dropped_text}],
    )
    monkeypatch.setattr(
        pipeline,
        "call_vlm_chunker",
        lambda **kwargs: {
            "chunks": [
                {
                    "chunk_text": "Some unrelated chunk the model did produce.",
                    "level_1_heading": "Doc Title",
                    "level_2_heading": "Some Section",
                }
            ]
        },
    )

    output_path = pipeline.process_pdf(
        client=object(), pdf_path=Path("document.pdf"), output_dir=tmp_path, model="test-model"
    )

    chunks = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    recovered = [c for c in chunks if c["chunk_text"] == dropped_text]

    assert len(recovered) == 1
    assert "Auto-recovered" in recovered[0]["source_notes"]
    # Inherits heading context from the chunk immediately before it.
    assert recovered[0]["level_1_heading"] == "Doc Title"
    assert recovered[0]["level_2_heading"] == "Some Section"
    assert "Recovered 1 block" in capsys.readouterr().out


def test_process_pdf_does_not_recover_when_coverage_is_good(tmp_path, monkeypatch, capsys):
    text = "Docling releases two highly capable AI models for layout analysis."
    monkeypatch.setattr(pipeline, "count_pages", lambda pdf_path: 1)
    monkeypatch.setattr(pipeline, "render_pdf_pages_to_base64", lambda **kwargs: [])
    monkeypatch.setattr(pipeline, "extract_page_text", lambda **kwargs: text)
    monkeypatch.setattr(
        pipeline, "extract_page_blocks", lambda **kwargs: [{"page_num": 1, "text": text}]
    )
    monkeypatch.setattr(pipeline, "extract_document_outline", _stub_outline)
    monkeypatch.setattr(pipeline, "call_vlm_chunker", lambda **kwargs: {"chunks": [{"chunk_text": text}]})

    output_path = pipeline.process_pdf(
        client=object(), pdf_path=Path("document.pdf"), output_dir=tmp_path, model="test-model"
    )

    chunks = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]

    assert len(chunks) == 1  # nothing extra got appended
    assert "Recovered" not in capsys.readouterr().out
