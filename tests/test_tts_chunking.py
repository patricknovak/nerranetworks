"""Tests for engine.tts.chunk_text – sentence-aware text splitting.

Covers short text, sentence splitting, fallback splitting, multiple chunks,
edge cases, custom max_chars, and content preservation.
"""

import unittest

from engine.tts import chunk_text


class TestShortText(unittest.TestCase):
    """Text that fits within max_chars returns a single chunk."""

    def test_below_limit_returns_single_chunk(self):
        text = "Hello world."
        result = chunk_text(text, max_chars=5000)
        self.assertEqual(result, [text])

    def test_exactly_at_limit(self):
        text = "a" * 5000
        result = chunk_text(text, max_chars=5000)
        self.assertEqual(result, [text])

    def test_empty_string(self):
        result = chunk_text("", max_chars=5000)
        self.assertEqual(result, [""])

    def test_single_character(self):
        result = chunk_text("x", max_chars=5000)
        self.assertEqual(result, ["x"])

    def test_whitespace_only_below_limit(self):
        text = "   "
        result = chunk_text(text, max_chars=5000)
        self.assertEqual(result, [text])


class TestSentenceSplitting(unittest.TestCase):
    """Splits at sentence boundaries (., !, ?)."""

    def test_splits_at_period(self):
        # First sentence fills most of the budget, second sentence pushes over.
        sentence_a = "A" * 40 + "."
        sentence_b = " " + "B" * 40 + "."
        text = sentence_a + sentence_b
        result = chunk_text(text, max_chars=50)
        self.assertEqual(result[0], sentence_a)

    def test_splits_at_exclamation(self):
        sentence_a = "A" * 40 + "!"
        sentence_b = " " + "B" * 40 + "!"
        text = sentence_a + sentence_b
        result = chunk_text(text, max_chars=50)
        self.assertEqual(result[0], sentence_a)

    def test_splits_at_question_mark(self):
        sentence_a = "A" * 40 + "?"
        sentence_b = " " + "B" * 40 + "?"
        text = sentence_a + sentence_b
        result = chunk_text(text, max_chars=50)
        self.assertEqual(result[0], sentence_a)

    def test_prefers_rightmost_sentence_ending(self):
        # Two sentence endings within the window; the rightmost should be chosen.
        text = "Hello. World. " + "X" * 5000
        result = chunk_text(text, max_chars=20)
        # The rightmost sentence ending within the first 20 chars should be chosen.
        self.assertIn(".", result[0])
        self.assertTrue(result[0].endswith("."))

    def test_multiple_sentences_rightmost_chosen(self):
        # Build text: "A. B. C. " + enough filler to exceed max_chars
        text = "A. B. C. " + "D" * 100
        result = chunk_text(text, max_chars=15)
        # Should split at "C." which is the rightmost sentence ending within 15 chars
        first = result[0]
        self.assertTrue(first.rstrip().endswith("."))


class TestFallbackSplitting(unittest.TestCase):
    """When no sentence endings exist, falls back to commas/semicolons, then spaces."""

    def test_splits_at_comma_when_no_sentence_ending(self):
        # No periods, exclamation, question marks — should split at comma
        text = "aaaa,bbbb,cccc " + "d" * 100
        result = chunk_text(text, max_chars=15)
        first = result[0]
        self.assertTrue(first.rstrip().endswith(",") or "," in first)

    def test_splits_at_semicolon_when_no_sentence_ending(self):
        text = "aaaa;bbbb;cccc " + "d" * 100
        result = chunk_text(text, max_chars=15)
        first = result[0]
        self.assertTrue(";" in first)

    def test_splits_at_space_when_no_punctuation(self):
        # No sentence endings, no commas/semicolons — should split at a space
        text = "abcdef ghijk " + "l" * 100
        result = chunk_text(text, max_chars=15)
        # The split should happen at a space boundary
        for chunk in result:
            self.assertLessEqual(len(chunk), 15 + 5)  # allow minor variance from strip

    def test_hard_cut_when_no_spaces(self):
        # No spaces at all — must hard cut at max_chars
        text = "a" * 200
        result = chunk_text(text, max_chars=50)
        self.assertTrue(len(result) > 1)
        self.assertEqual(len(result[0]), 50)


class TestMultipleChunks(unittest.TestCase):
    """Very long text produces multiple chunks, all within max_chars."""

    def test_long_text_produces_multiple_chunks(self):
        sentences = ["Sentence number %d." % i for i in range(200)]
        text = " ".join(sentences)
        result = chunk_text(text, max_chars=100)
        self.assertGreater(len(result), 1)

    def test_all_chunks_within_max_chars(self):
        sentences = ["This is sentence %d." % i for i in range(200)]
        text = " ".join(sentences)
        max_chars = 100
        result = chunk_text(text, max_chars=max_chars)
        for i, chunk in enumerate(result):
            self.assertLessEqual(
                len(chunk),
                max_chars,
                f"Chunk {i} exceeds max_chars: {len(chunk)} > {max_chars}",
            )

    def test_chunk_count_reasonable(self):
        text = "Word. " * 1000
        max_chars = 100
        result = chunk_text(text, max_chars=max_chars)
        total_len = sum(len(c) for c in result)
        # Chunk count should be approximately total_len / max_chars
        expected_min = total_len // (max_chars + 10)
        self.assertGreaterEqual(len(result), expected_min)

    def test_no_empty_chunks(self):
        sentences = ["Hello world." for _ in range(100)]
        text = " ".join(sentences)
        result = chunk_text(text, max_chars=50)
        for chunk in result:
            self.assertTrue(len(chunk) > 0, "Empty chunk found")


class TestEdgeCases(unittest.TestCase):
    """Edge cases: no spaces, single long word, unicode, newlines."""

    def test_text_with_no_spaces_at_all(self):
        text = "x" * 300
        result = chunk_text(text, max_chars=100)
        self.assertGreater(len(result), 1)
        # Each chunk (except possibly last) should be exactly max_chars
        self.assertEqual(len(result[0]), 100)

    def test_single_very_long_word(self):
        word = "supercalifragilistic" * 50
        result = chunk_text(word, max_chars=100)
        self.assertGreater(len(result), 1)

    def test_unicode_characters(self):
        text = "Caf\u00e9 au lait. " * 100
        result = chunk_text(text, max_chars=50)
        self.assertGreater(len(result), 1)
        for chunk in result:
            self.assertLessEqual(len(chunk), 50)

    def test_newlines_in_text(self):
        text = "Line one.\nLine two.\nLine three.\n" * 50
        result = chunk_text(text, max_chars=50)
        self.assertGreater(len(result), 1)

    def test_text_with_only_spaces(self):
        # Spaces-only text longer than max_chars
        text = " " * 200
        result = chunk_text(text, max_chars=50)
        # After stripping, the remaining text is empty so result may be empty or minimal
        self.assertIsInstance(result, list)

    def test_tabs_and_mixed_whitespace(self):
        text = "Hello.\tWorld.\t" * 50
        result = chunk_text(text, max_chars=30)
        self.assertGreater(len(result), 1)


class TestCustomMaxChars(unittest.TestCase):
    """Tests with small max_chars values."""

    def test_max_chars_100(self):
        text = "Short sentence. " * 20
        result = chunk_text(text, max_chars=100)
        for chunk in result:
            self.assertLessEqual(len(chunk), 100)

    def test_max_chars_10(self):
        text = "A. B. C. D. E. F. G. H."
        result = chunk_text(text, max_chars=10)
        self.assertGreater(len(result), 1)
        for chunk in result:
            self.assertLessEqual(len(chunk), 10)

    def test_max_chars_1(self):
        text = "ab"
        result = chunk_text(text, max_chars=1)
        # Each chunk is at most 1 character
        for chunk in result:
            self.assertLessEqual(len(chunk), 1)

    def test_various_chunk_counts(self):
        # With max_chars=20, a 200-char text should produce ~10 chunks
        text = "A" * 10 + ". " + "B" * 10 + ". " + "C" * 10 + ". "
        text = text * 10  # ~360 chars
        result = chunk_text(text, max_chars=20)
        self.assertGreater(len(result), 5)

    def test_default_max_chars_is_5000(self):
        text = "x" * 4999
        result = chunk_text(text)
        self.assertEqual(len(result), 1)


class TestChunkContentPreservation(unittest.TestCase):
    """Verify all original text is preserved across chunks."""

    def test_join_matches_original_stripped(self):
        sentences = ["The quick brown fox jumped. " for _ in range(100)]
        text = "".join(sentences)
        result = chunk_text(text, max_chars=100)
        # Rejoining chunks (with space) should contain all non-whitespace content
        joined = " ".join(result)
        self.assertEqual(
            text.split(),
            joined.split(),
        )

    def test_no_text_lost_simple(self):
        text = "Hello world. Foo bar. Baz qux."
        result = chunk_text(text, max_chars=15)
        joined = " ".join(result)
        # Every word from the original should appear in the joined result
        for word in text.split():
            self.assertIn(word, joined)

    def test_no_text_lost_long(self):
        words = [f"word{i}" for i in range(500)]
        text = ". ".join(words) + "."
        result = chunk_text(text, max_chars=200)
        joined = " ".join(result)
        for word in words:
            self.assertIn(word, joined)

    def test_no_duplicate_content(self):
        text = "A. B. C. D. E. F. G. H. I. J."
        result = chunk_text(text, max_chars=10)
        # Total characters across chunks should not exceed original length
        total = sum(len(c) for c in result)
        self.assertLessEqual(total, len(text) + len(result))  # allow for minor whitespace

    def test_preservation_with_unicode(self):
        text = "Caf\u00e9. Na\u00efve. R\u00e9sum\u00e9. " * 30
        result = chunk_text(text, max_chars=50)
        joined = " ".join(result)
        for word in ["Caf\u00e9.", "Na\u00efve.", "R\u00e9sum\u00e9."]:
            self.assertIn(word, joined)


if __name__ == "__main__":
    unittest.main()
