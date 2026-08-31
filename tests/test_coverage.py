from vich.chunking.coverage import coverage_ratio


def test_coverage_ratio_full_when_chunks_repeat_the_source():
    text = "Docling releases two highly capable AI models for layout analysis."
    assert coverage_ratio(text, [text]) == 1.0


def test_coverage_ratio_partial_when_a_paragraph_is_missing():
    extracted = (
        "Converting documents back into a unified machine-processable format "
        "has been a major challenge for decades due to variability in formats. "
        "Document conversion is a well-established field with numerous solutions."
    )
    # Only the second sentence made it into the chunk -- the first vanished.
    chunk_texts = ["Document conversion is a well-established field with numerous solutions."]

    ratio = coverage_ratio(extracted, chunk_texts)

    assert 0.0 < ratio < 0.7


def test_coverage_ratio_is_one_for_text_with_no_significant_words():
    # Blank/near-blank page: nothing to cover, so nothing can be under-covered.
    assert coverage_ratio("", ["anything"]) == 1.0
    assert coverage_ratio("1 2 3 - a an", ["anything"]) == 1.0


def test_coverage_ratio_zero_when_chunks_are_unrelated():
    extracted = "Table structure recognition uses a vision transformer model."
    chunk_texts = ["Completely different sentence about something else entirely."]

    assert coverage_ratio(extracted, chunk_texts) == 0.0


def test_coverage_ratio_is_case_insensitive():
    assert coverage_ratio("Docling Document", ["docling document"]) == 1.0
