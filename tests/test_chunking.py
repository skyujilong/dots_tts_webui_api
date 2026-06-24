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


def test_backs_off_to_first_english_period_when_newline_exceeds_max():
    text = "a" * 12 + "." + "b" * 20 + "\ntail"
    chunks = chunk_text_by_newline(text, min_chars=10, max_chars=20)
    assert chunks[0].text == "a" * 12 + "."
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == 13
    assert all(len(chunk.text) <= 20 for chunk in chunks)


def test_backs_off_to_first_chinese_period_when_newline_exceeds_max():
    text = "你" * 12 + "。" + "我" * 20 + "\n尾"
    chunks = chunk_text_by_newline(text, min_chars=10, max_chars=20)
    assert chunks[0].text == "你" * 12 + "。"
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == 13
    assert all(len(chunk.text) <= 20 for chunk in chunks)


def test_backs_off_to_exclamation_when_newline_exceeds_max():
    # 长句以中文感叹号收尾：回退应认 ！，不被迫推到 max 处硬截断
    text = "你" * 12 + "！" + "我" * 20 + "\n尾"
    chunks = chunk_text_by_newline(text, min_chars=10, max_chars=20)
    assert chunks[0].text == "你" * 12 + "！"
    assert chunks[0].char_end == 13
    assert all(len(chunk.text) <= 20 for chunk in chunks)


def test_backs_off_to_question_mark_when_newline_exceeds_max():
    # 英文问号同样作为回退切点
    text = "a" * 12 + "?" + "b" * 20 + "\ntail"
    chunks = chunk_text_by_newline(text, min_chars=10, max_chars=20)
    assert chunks[0].text == "a" * 12 + "?"
    assert chunks[0].char_end == 13
    assert all(len(chunk.text) <= 20 for chunk in chunks)


def test_backs_off_to_earliest_sentence_end_regardless_of_type():
    # 窗口内 ！ 比 。 更靠前时，应在更早的 ！ 处回退（取最早句末标点）
    text = "a" * 12 + "！" + "b" * 3 + "。" + "c" * 20 + "\ntail"
    chunks = chunk_text_by_newline(text, min_chars=10, max_chars=25)
    assert chunks[0].text == "a" * 12 + "！"
    assert all(len(chunk.text) <= 25 for chunk in chunks)


def test_backs_off_to_first_period_after_min_not_last_before_max():
    text = "a" * 12 + "." + "b" * 3 + "." + "c" * 20 + "\ntail"
    chunks = chunk_text_by_newline(text, min_chars=10, max_chars=25)
    assert chunks[0].text == "a" * 12 + "."
    assert all(len(chunk.text) <= 25 for chunk in chunks)


def test_preserves_max_cap_when_no_period_before_max():
    text = "a" * 25 + "\ntail"
    chunks = chunk_text_by_newline(text, min_chars=10, max_chars=20)
    assert chunks[0].text == "a" * 20
    assert chunks[1].text == "a" * 5
    assert all(len(chunk.text) <= 20 for chunk in chunks)


def test_does_not_backoff_to_period_beyond_max():
    text = "a" * 25 + ".\ntail"
    chunks = chunk_text_by_newline(text, min_chars=10, max_chars=20)
    assert chunks[0].text == "a" * 20
    assert all(len(chunk.text) <= 20 for chunk in chunks)


def test_blank_input_produces_no_chunks():
    assert chunk_text_by_newline("\n  \n", min_chars=1, max_chars=10) == []
