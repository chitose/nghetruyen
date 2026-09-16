import unittest
from chunker import build_paragraph_chunks, join_short_paragraphs, split_into_chunks


class TestSplitIntoChunks(unittest.TestCase):
    def test_basic_sentence_split(self):
        self.assertEqual(
            split_into_chunks("Xin chào. Tôi khỏe. Cảm ơn!"),
            ["Xin chào.", "Tôi khỏe.", "Cảm ơn!"],
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

    def test_long_run_on_sentence_splits_on_word_boundaries(self):
        long_text = "từ " * 200 + "."
        chunks = split_into_chunks(long_text, 50)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), 50)
        import re
        rejoined = re.sub(r"\s+", " ", " ".join(chunks))
        expected = re.sub(r"\s+", " ", long_text.strip())
        self.assertEqual(rejoined, expected)

    def test_single_word_longer_than_max_len_still_emitted(self):
        no_spaces = "a" * 500 + "."
        chunks = split_into_chunks(no_spaces, 100)
        self.assertGreaterEqual(len(chunks), 5)

    def test_curly_quote_handling(self):
        self.assertEqual(
            split_into_chunks('She said "go." Then left.'),
            ['She said "go."', 'Then left.'],
        )


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
                ("Câu một.", 0),
                ("Câu hai.", 0),
                ("Đoạn hai chỉ có một câu.", 1),
                ("Đoạn ba.", 2),
            ],
        )


if __name__ == "__main__":
    unittest.main()
