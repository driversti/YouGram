from yougram.chunking import split_message


def test_short_text_is_one_chunk():
    assert split_message("hello", limit=10) == ["hello"]


def test_text_at_exactly_limit_is_one_chunk():
    text = "a" * 10
    assert split_message(text, limit=10) == [text]


def test_prefers_to_split_on_newline_boundary():
    # "line1\nline2" is 11 chars; adding "\nline3" overflows limit=12.
    chunks = split_message("line1\nline2\nline3", limit=12)
    assert chunks == ["line1\nline2", "line3"]


def test_long_line_splits_on_word_boundaries_without_breaking_words():
    chunks = split_message("aaa bbb ccc ddd", limit=7)
    assert chunks == ["aaa", "bbb", "ccc ddd"]
    assert all(" " not in c or len(c) <= 7 for c in chunks)


def test_single_word_longer_than_limit_is_hard_split():
    chunks = split_message("a" * 25, limit=10)
    assert chunks == ["a" * 10, "a" * 10, "a" * 5]


def test_every_chunk_is_within_the_limit():
    text = "word " * 5000  # ~25k chars
    chunks = split_message(text, limit=4000)
    assert len(chunks) > 1
    assert all(len(c) <= 4000 for c in chunks)


def test_no_empty_chunks_emitted():
    chunks = split_message("a\n\n\n" + "b" * 30, limit=10)
    assert all(c != "" for c in chunks)


def test_default_limit_is_below_telegram_max():
    # Telegram rejects messages over 4096 (UTF-16) units; we leave headroom.
    long_line = "x" * 5000
    chunks = split_message(long_line)
    assert all(len(c) <= 4000 for c in chunks)
