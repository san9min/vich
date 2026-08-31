from vich.chunking.recovery import find_missed_blocks


def test_find_missed_blocks_flags_a_dropped_paragraph():
    blocks = [
        {
            "page_num": 1,
            "text": (
                "Converting documents back into a unified machine-processable format "
                "has been a major challenge for decades due to variability in formats "
                "and weak standardization across the industry as a whole."
            ),
        }
    ]
    chunk_texts = ["Some completely unrelated chunk about a different topic entirely."]

    missed = find_missed_blocks(blocks, chunk_texts)

    assert missed == blocks


def test_find_missed_blocks_ignores_a_block_that_is_covered():
    text = (
        "Converting documents back into a unified machine-processable format "
        "has been a major challenge for decades due to variability in formats."
    )
    blocks = [{"page_num": 1, "text": text}]

    assert find_missed_blocks(blocks, [text]) == []


def test_find_missed_blocks_ignores_short_fragments():
    # A page number, running header, or caption fragment shouldn't be
    # treated as a dropped paragraph even if it matches nothing.
    blocks = [{"page_num": 3, "text": "Page 3 of 12"}]

    assert find_missed_blocks(blocks, ["anything else entirely"]) == []


def test_find_missed_blocks_handles_no_blocks():
    assert find_missed_blocks([], ["some chunk text"]) == []
