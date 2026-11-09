"""Regression coverage for portable records and the three retest selections."""

from copy import deepcopy
from pathlib import Path
import random
import unittest

import morphology
import quiz_record
import vocab


VAULT = Path(__file__).resolve().parent.parent


def answers_for(kind, questions):
    return [{**({"main": q["answer"].split(" / ")[0]} if kind == "vocabulary" else {}),
             "fields": {f["key"]: f["answer"].split(" / ")[0] for f in q["fields"]}}
            for q in questions]


class Records(unittest.TestCase):
    def test_roundtrip_preserves_random_directions_repeats_and_answer_variants(self):
        pool = vocab.load_vault(VAULT)["ch1.md"]
        opts = dict(files=["ch1.md"], count=50, mode="mixed", parsing=True, exhaustive=False, shuffle=True)
        questions = vocab.build_quiz(pool, 50, "mixed", True, random.Random(17))
        record = quiz_record.make_record("vocabulary", opts, questions)
        restored = quiz_record.loads(quiz_record.dumps(record).encode("utf-8"))
        self.assertEqual(restored["configuration"], opts)
        self.assertEqual(restored["questions"], questions)
        self.assertEqual({q["direction"] for q in questions}, {"la_to_en", "en_to_la"})
        self.assertLess(len({q["entry_key"] for q in questions}), len(questions))
        self.assertEqual(vocab.grade(questions, answers_for("vocabulary", questions)),
                         vocab.grade(restored["questions"], answers_for("vocabulary", questions)))
        questions[0]["unfamiliar"] = True
        questions[0]["given"] = "previous answer"
        record = quiz_record.make_record("vocabulary", opts, questions)
        self.assertNotIn("unfamiliar", record["questions"][0])
        self.assertNotIn("given", record["questions"][0])

    def test_morphology_snapshot_preserves_pairs_genders_tenses_and_disabled_cells(self):
        pool = vocab.load_vault(VAULT)["ch10.md"]
        opts = {"files": ["ch10.md"], **morphology.options({"exhaustive": True,
                "tenses": ["present", "imperfect"], "moods": ["indicative", "subjunctive"]})}
        questions = morphology.build_quiz(pool, opts, random.Random(4))["questions"]
        record = quiz_record.loads(quiz_record.dumps(quiz_record.make_record("morphology", opts, questions)))
        self.assertEqual(record["questions"], questions)
        self.assertEqual(record["configuration"], opts)
        self.assertTrue(any(q["kind"] == "pair" for q in questions))
        self.assertTrue(any(f["disabled"] for q in questions for f in q["fields"]))
        self.assertEqual(morphology.grade(questions, answers_for("morphology", questions)),
                         morphology.grade(record["questions"], answers_for("morphology", questions)))

    def test_invalid_uploads_have_useful_errors(self):
        for bad in (b"not JSON", b"\xff", "{}", "[]", '{"format":"latin-quiz-record","version":2}'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                quiz_record.loads(bad)
        opts = dict(files=["ch1.md"], count=1, mode="mixed", parsing=True, exhaustive=False, shuffle=True)
        qs = vocab.build_quiz(vocab.load_vault(VAULT)["ch1.md"], 1, "mixed", True)
        record = quiz_record.make_record("vocabulary", opts, qs)
        for change in ({"index": -1}, {"fields": [{}]}, {"accepted": "wrong type"}):
            bad = deepcopy(record)
            bad["questions"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                quiz_record.validate(bad)

    def test_review_order_prioritizes_flags_then_parsing_errors_and_accepts_macron_slips(self):
        results = [{"index": 0, "verdict": "correct", "fields": []},
                   {"index": 1, "verdict": "macrons", "fields": []},
                   {"index": 2, "verdict": "correct", "fields": [{"verdict": "wrong"}]},
                   {"index": 3, "verdict": "wrong", "fields": []}]
        first, rest = quiz_record.review_groups(results, [0, 3])
        self.assertEqual([r["index"] for r in first], [0, 3])
        self.assertEqual([r["index"] for r in rest], [2, 1])
        self.assertEqual([r["index"] for r in quiz_record.review_groups(results, [])[1]], [2, 3, 0, 1])


if __name__ == "__main__":
    unittest.main()
