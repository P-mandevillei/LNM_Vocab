"""Vocabulary prompt qualifiers and answer matching regressions."""

from pathlib import Path
import unittest

import vocab


VAULT = Path(__file__).resolve().parent.parent


class EnglishPromptQualifiers(unittest.TestCase):
    def test_chapter12_number_qualifiers_are_visible(self):
        pool = vocab.load_vault(VAULT)["ch12.md"]
        chosen = [entry for entry in pool
                  if vocab.normalize(entry.headword) in {"tuus", "vester", "vos"}]
        questions = vocab.make_questions(chosen, pool, "en_to_la", True)
        self.assertEqual(len(questions), 3)
        for question, entry in zip(questions, chosen):
            with self.subTest(headword=entry.headword):
                self.assertEqual(question["prompt"], entry.english)
                self.assertRegex(question["prompt"], r"\((?:sg|pl)\.\)")

    def test_singular_and_plural_prompts_have_distinct_answers(self):
        for singular, plural in [("sg.", "pl."), ("sing.", "plural"),
                                 ("singular", "PL.")]:
            with self.subTest(singular=singular, plural=plural):
                pool = [vocab.Entry(["tū"], f"you ({singular})", "pronoun", "ch.md", 1),
                        vocab.Entry(["vōs"], f"you ({plural})", "pronoun", "ch.md", 2)]
                questions = vocab.make_questions(pool, pool, "en_to_la", False)
                for question, entry in zip(questions, pool):
                    self.assertEqual(question["prompt"], entry.english)
                correct = vocab.grade(questions, [{"main": "tū"}, {"main": "vōs"}])
                swapped = vocab.grade(questions, [{"main": "vōs"}, {"main": "tū"}])
                self.assertEqual(correct["score"]["main_correct"], 2)
                self.assertEqual(swapped["score"]["main_correct"], 0)

    def test_explanatory_notes_stay_optional_with_qualified_twins(self):
        pool = [vocab.Entry(["tū"], "you (sg.) (a personal pronoun)", "pronoun", "ch.md", 1),
                vocab.Entry(["tūte"], "you (sg.)", "pronoun", "ch.md", 2)]
        question = vocab.make_questions(pool[:1], pool, "en_to_la", False)[0]
        self.assertEqual(question["prompt"], "you (sg.)")
        self.assertIn("tu", question["accepted"])
        self.assertIn("tute", question["accepted"])

    def test_latin_to_english_still_accepts_bare_meaning(self):
        entry = vocab.Entry(["vōs"], "you (pl.)", "pronoun", "ch.md", 1)
        questions = vocab.make_questions([entry], [entry], "la_to_en", False)
        self.assertEqual(questions[0]["prompt"], "vōs")
        for answer in ["you", "you (pl.)"]:
            with self.subTest(answer=answer):
                result = vocab.grade(questions, [{"main": answer}])
                self.assertEqual(result["score"]["main_correct"], 1)


if __name__ == "__main__":
    unittest.main()
