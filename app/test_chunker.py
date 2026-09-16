import re
import unittest
from chunker import (
    build_paragraph_chunks,
    join_short_paragraphs,
    split_into_chunks,
    split_text,
)


def normalized(text):
    return re.sub(r"\s+", " ", text).strip()


def rejoined(chunks):
    """Put chunks back together the way a reader would hear them: a chunk is
    stripped of the whitespace at the cut, so the only word boundary that can
    need restoring is between two word characters."""
    text = ""
    for chunk in chunks:
        if text and text[-1].isalnum() and chunk[:1].isalnum():
            text += " "
        text += chunk
    return normalized(text)


class TestSplitIntoChunks(unittest.TestCase):
    def test_sentences_of_one_paragraph_share_a_chunk_when_they_fit(self):
        # The gist merges pieces back up to chunk_size, so a short Paragraph is
        # one chunk rather than one chunk per sentence.
        self.assertEqual(
            split_into_chunks("Xin chào. Tôi khỏe. Cảm ơn!"),
            ["Xin chào. Tôi khỏe. Cảm ơn!"],
        )

    def test_no_terminal_punctuation_is_one_chunk(self):
        self.assertEqual(split_into_chunks("không có dấu chấm"), ["không có dấu chấm"])

    def test_vietnamese_ellipsis_and_quote_handling(self):
        self.assertEqual(
            split_into_chunks('Anh nói "đi thôi…" rồi bước ra.'),
            ['Anh nói "đi thôi…" rồi bước ra.'],
        )

    def test_empty_or_whitespace_only_input(self):
        self.assertEqual(split_into_chunks("   "), [])

    def test_every_chunk_fits_the_limit(self):
        chunks = split_into_chunks("từ " * 200 + ".", 50)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 50)

    def test_splitting_keeps_all_the_text(self):
        text = "Một câu dài dòng. " * 20
        chunks = split_into_chunks(text, 120)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(rejoined(chunks), normalized(text))

    def test_single_word_longer_than_max_len_still_emitted(self):
        no_spaces = "a" * 500 + "."
        chunks = split_into_chunks(no_spaces, 100)
        self.assertGreaterEqual(len(chunks), 5)

    def test_curly_quote_handling(self):
        self.assertEqual(
            split_into_chunks('She said "go." Then left.'),
            ['She said "go." Then left.'],
        )

    def test_abbreviation_before_a_proper_noun_can_still_split(self):
        # Documented limitation: "T.S." is followed by a capital, so the
        # sentence guard sees a new sentence. A decimal, which is the other
        # common false cut, is guarded (see the next test).
        self.assertEqual(
            split_into_chunks("T.S. Eliot viết.", 8),
            ["T.S.", "Eliot", "viết."],
        )

    def test_decimals_do_not_end_a_sentence(self):
        self.assertEqual(split_into_chunks("Pi là 3.14 nhé."), ["Pi là 3.14 nhé."])

    def test_a_sentence_is_not_cut_before_its_own_lowercase_words(self):
        # The old chunker only cut before an uppercase letter; the guard
        # replaces that rule, so "rồi" stays with the sentence it belongs to.
        self.assertEqual(
            split_into_chunks("Anh ấy nói thôi. rồi im lặng."),
            ["Anh ấy nói thôi. rồi im lặng."],
        )

    def test_line_breaks_split_before_sentence_punctuation_does(self):
        chunks = split_into_chunks("Câu một.\nCâu hai.", 8)
        self.assertEqual(chunks, ["Câu một.", "Câu hai."])

    def test_a_paragraph_is_cut_at_the_best_available_boundary(self):
        text = "Đoạn này dài hơn giới hạn, nên nó phải được cắt ở đâu đó."
        chunks = split_into_chunks(text, 30)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 30)
        self.assertEqual(rejoined(chunks), normalized(text))


class TestSplitText(unittest.TestCase):
    """The splitter's own knobs, which `split_into_chunks` fixes to its TTS
    configuration."""

    def test_the_top_separator_decides_where_a_chunk_may_end(self):
        text = "Một câu dài dòng, với nhiều mệnh đề, ở trong đó."
        chunks = split_text(text, chunk_size=20)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 20)
        self.assertEqual(rejoined(chunks), normalized(text))

    def test_overlap_repeats_the_tail_of_one_chunk_at_the_start_of_the_next(self):
        chunks = split_text("từ " * 40 + ".", chunk_size=50, chunk_overlap=20)
        self.assertGreater(len(chunks), 2)
        shared = chunks[0][-5:]
        self.assertTrue(
            any(shared in chunk[1:] and chunk.startswith(shared) for chunk in chunks[1:]),
            f"no chunk starts with the tail {shared!r}",
        )

    def test_overlap_larger_than_the_chunk_size_is_refused(self):
        with self.assertRaises(ValueError):
            split_text("anything", chunk_size=10, chunk_overlap=11)

    def test_separators_can_be_given_as_literals(self):
        # `is_separator_regex=False` escapes each Separator, so a plain string
        # like "|" is a literal rather than an alternation.
        chunks = split_text("a|b|c", chunk_size=2, separators=["|", ""], is_separator_regex=False)
        self.assertEqual(normalized("".join(chunks)), "a|b|c")
        self.assertGreater(len(chunks), 1)


class TestJoinShortParagraphs(unittest.TestCase):
    def test_a_short_paragraph_joins_the_next_one(self):
        self.assertEqual(
            join_short_paragraphs(["Ngắn thôi.", "Đây là một đoạn dài hơn nhiều từ."], 6),
            ["Ngắn thôi. Đây là một đoạn dài hơn nhiều từ."],
        )

    def test_a_long_paragraph_is_left_alone(self):
        self.assertEqual(
            join_short_paragraphs(["Một đoạn dài đủ số từ cần thiết.", "Ngắn."], 5),
            ["Một đoạn dài đủ số từ cần thiết.", "Ngắn."],
        )

    def test_a_run_of_short_paragraphs_keeps_joining_until_long_enough(self):
        self.assertEqual(
            join_short_paragraphs(["a b", "c d", "e f", "g h"], 5),
            ["a b c d e f", "g h"],
        )

    def test_joined_paragraphs_are_separated_by_one_space(self):
        self.assertEqual(
            join_short_paragraphs(["one", "two three four five"], 6),
            ["one two three four five"],
        )

    def test_blank_paragraphs_are_dropped(self):
        self.assertEqual(join_short_paragraphs(["", "   ", "a b c"], 3), ["a b c"])

    def test_a_trailing_short_paragraph_is_kept(self):
        self.assertEqual(join_short_paragraphs(["a b c", "d"], 5), ["a b c d"])

    def test_a_threshold_of_one_leaves_paragraphs_alone(self):
        self.assertEqual(join_short_paragraphs(["a", "b"], 1), ["a", "b"])


class TestBuildParagraphChunks(unittest.TestCase):
    def test_sentences_tagged_with_source_paragraph_and_never_merged_across_boundary(self):
        chunks = build_paragraph_chunks([
            "Câu một. Câu hai.",
            "Đoạn hai chỉ có một câu.",
            "",
            "Đoạn ba.",
        ])
        self.assertEqual(
            [(c["text"], c["paragraphIndex"]) for c in chunks],
            [
                ("Câu một. Câu hai.", 0),
                ("Đoạn hai chỉ có một câu.", 1),
                ("Đoạn ba.", 2),
            ],
        )

    def test_a_long_paragraph_yields_several_chunks_sharing_one_index(self):
        chunks = build_paragraph_chunks(["từ " * 60], 50)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk["text"]), 50)
            self.assertEqual(chunk["paragraphIndex"], 0)


if __name__ == "__main__":
    unittest.main()
