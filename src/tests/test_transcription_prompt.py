"""Tests for the versioned handwriting-transcription prompt."""

import unittest

from src.submissions.transcription.prompt import (
    HANDWRITING_PROMPT_SHA256,
    HANDWRITING_PROMPT_VERSION,
    HANDWRITING_TRANSCRIPTION_PROMPT,
)


class TestHandwritingPrompt(unittest.TestCase):
    def test_prompt_version_and_hash_are_stable(self):
        self.assertEqual(HANDWRITING_PROMPT_VERSION, "1.0")
        self.assertEqual(len(HANDWRITING_PROMPT_SHA256), 64)

    def test_prompt_contains_safety_invariants(self):
        prompt = HANDWRITING_TRANSCRIPTION_PROMPT
        self.assertIn("Do not solve the problem.", prompt)
        self.assertIn("Do not correct the student's answer.", prompt)
        self.assertIn("Do not infer missing text.", prompt)
        self.assertIn("[ILLEGIBLE]", prompt)
        self.assertIn("Return only the transcription.", prompt)
        self.assertIn("Preserve pseudocode structure and indentation.", prompt)
        self.assertIn("Ω(n)", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
