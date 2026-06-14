from dots_tts_webui_api.chunking import chunk_text_by_newline, preprocess_text


def test_preprocess_removes_blank_lines_and_normalizes_newlines():
    assert preprocess_text("a\r\n\n  \n b\rc") == "a\n b\nc"


def test_splits_after_min_chars_on_newline():
    chunks = chunk_text_by_newline("aaa\nbbb\nccc", min_chars=5, max_chars=20)
    assert [chunk.text for chunk in chunks] == ["aaa\nbbb", "ccc"]
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == 7


def test_no_newline_short_text_is_not_hard_split():
    chunks = chunk_text_by_newline("short no newline", min_chars=180, max_chars=1200)
    assert len(chunks) == 1
    assert chunks[0].text == "short no newline"


def test_max_chars_soft_split_fallback():
    long = "a" * 10 + "。" + "b" * 10 + "。" + "c" * 10
    chunks = chunk_text_by_newline(long, min_chars=1, max_chars=12)
    assert len(chunks) >= 3
    assert all(len(chunk.text) <= 12 for chunk in chunks)


def test_blank_input_produces_no_chunks():
    assert chunk_text_by_newline("\n  \n", min_chars=1, max_chars=10) == []
