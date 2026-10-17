"""Compact Streamlit records reconstruct from installed chapter/morphology data."""

from copy import deepcopy
import json
from pathlib import Path
import random
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import morphology
import quiz_record
import vocab


VAULT = Path(__file__).resolve().parent.parent


class ReferenceRecords(unittest.TestCase):
    def vocabulary(self, count=50):
        pool = vocab.load_vault(VAULT)["ch1.md"]
        opts = dict(files=["ch1.md"], count=count, mode="mixed", parsing=True,
                    exhaustive=False, shuffle=True)
        questions = vocab.build_quiz(pool, count, "mixed", True, random.Random(17))
        return opts, questions

    def test_mixed_directions_repeated_entries_and_order_roundtrip(self):
        opts, questions = self.vocabulary()
        record = quiz_record.make_record("vocabulary", opts, questions, compact=True)
        encoded = quiz_record.dumps(record).encode("utf-8")
        restored = quiz_record.reconstruct(quiz_record.loads(encoded), VAULT)
        self.assertEqual(restored, questions)
        self.assertEqual(record["version"], 2)
        self.assertEqual(record["configuration"], opts)
        self.assertTrue(all(set(ref) == {"entry", "direction"} for ref in record["questions"]))
        self.assertEqual({q["direction"] for q in restored}, {"la_to_en", "en_to_la"})
        self.assertLess(len({q["entry_key"] for q in restored}), len(restored))
        legacy = quiz_record.make_record("vocabulary", opts, questions)
        self.assertLess(len(encoded), len(quiz_record.dumps(legacy).encode("utf-8")) / 5)

    def test_vocabulary_twins_use_the_full_selected_pool(self):
        pool = [vocab.Entry(["amo"], "love", "verb", "ch.md", 1, key="ch.md:1"),
                vocab.Entry(["diligo"], "love", "verb", "ch.md", 2, key="ch.md:2")]
        opts = dict(files=["ch.md"], count=1, mode="en_to_la", parsing=False,
                    exhaustive=False, shuffle=False)
        questions = vocab.make_questions([pool[0]], pool, "en_to_la", False)
        record = quiz_record.make_record("vocabulary", opts, questions, compact=True)
        with patch.object(vocab, "load_vault", return_value={"ch.md": pool}):
            restored = quiz_record.reconstruct(record, VAULT)
        self.assertEqual(restored, questions)
        self.assertIn("diligo", restored[0]["accepted"])

    def test_all_morphology_types_and_recorded_random_choices_roundtrip(self):
        chapters = vocab.load_vault(VAULT)
        pool = [entry for entries in chapters.values() for entry in entries]
        opts = {"files": list(chapters), **morphology.options({
            "count": 500, "tenses": list(morphology.TENSES), "moods": list(morphology.MOODS)})}
        questions = morphology.build_quiz(pool, opts, random.Random(17))["questions"]
        record = quiz_record.make_record("morphology", opts, questions, compact=True)
        restored = quiz_record.reconstruct(quiz_record.loads(quiz_record.dumps(record)), VAULT)
        self.assertEqual(restored, questions)
        self.assertEqual(morphology.grade(restored, []), morphology.grade(questions, []))
        self.assertEqual({q["kind"] for q in restored}, set(morphology.KINDS))
        self.assertTrue(any(q["kind"] == "pair" and q["entry"].split(":")[0]
                            != q["adjective"].split(":")[0] for q in record["questions"]))
        self.assertTrue(any(field["disabled"] for q in restored for field in q["fields"]))
        self.assertGreater(len({(q["voice"], q["tense"], q["mood"])
                                for q in restored if q["kind"] == "verb"}), 6)
        self.assertTrue(all("fields" not in ref and "answer" not in ref for ref in record["questions"]))
        legacy = quiz_record.make_record("morphology", opts, questions)
        self.assertLess(len(quiz_record.dumps(record)), len(quiz_record.dumps(legacy)) / 20)

    def test_retest_keeps_its_subset_order_directions_and_settings(self):
        opts, questions = self.vocabulary()
        questions = morphology.retest(questions, [4, 0, 8], random.Random(5))
        opts.update(count=3, exhaustive=False, retest_selection="combined")
        record = quiz_record.make_record("vocabulary", opts, questions, retest=True, compact=True)
        self.assertTrue(record["retest"])
        self.assertEqual(record["configuration"]["retest_selection"], "combined")
        self.assertEqual(quiz_record.reconstruct(record, VAULT), questions)

    def test_results_store_positions_scores_and_flags_without_responses(self):
        for kind in ("vocabulary", "morphology"):
            if kind == "vocabulary":
                pool = vocab.load_vault(VAULT)["ch10.md"]
                opts = dict(files=["ch10.md"], count=4, mode="en_to_la", parsing=True,
                            exhaustive=False, shuffle=False)
                questions = vocab.make_questions([entry for entry in pool if entry.pos == "noun"][:4],
                                                  pool, "en_to_la", True)
                grader = vocab.grade
            else:
                opts = {"files": ["ch10.md"], **morphology.options({"count": 4})}
                questions = morphology.build_quiz(vocab.load_vault(VAULT)["ch10.md"],
                                                  opts, random.Random(4))["questions"]
                grader = morphology.grade
            answers = [{**({"main": q["answer"].split(" / ")[0]} if kind == "vocabulary" else {}),
                        "fields": {f["key"]: f["answer"].split(" / ")[0] for f in q["fields"]},
                        "unfamiliar": q["index"] == 2} for q in questions]
            if kind == "vocabulary":
                answers[0]["main"] = "private response to omit"
                first_wrong = "main"
            else:
                first_wrong = next(f["key"] for f in questions[0]["fields"] if not f["disabled"])
                answers[0]["fields"][first_wrong] = "private response to omit"
            second_wrong = next(f["key"] for f in questions[1]["fields"] if not f.get("disabled"))
            answers[1]["fields"][second_wrong] = "another private response"
            graded = grader(questions, answers)
            record = quiz_record.make_record(kind, opts, questions, compact=True)
            completed = quiz_record.with_result(record, questions, graded)
            encoded = quiz_record.dumps(completed)
            self.assertNotIn("private response", encoded)
            self.assertNotIn('"given"', encoded)
            self.assertEqual(completed["result"], {"score": graded["score"],
                             "wrong": {"0": [first_wrong], "1": [second_wrong]}, "unfamiliar": [2]})
            self.assertEqual(quiz_record.reconstruct(quiz_record.loads(encoded), VAULT), questions)
            self.assertNotIn("result", record)

    def test_invalid_references_and_results_are_rejected(self):
        opts, questions = self.vocabulary(4)
        record = quiz_record.make_record("vocabulary", opts, questions, compact=True)
        for change in ({"entry": None}, {"entry": ""}, {"direction": []}, {"direction": "mixed"}):
            bad = deepcopy(record)
            bad["questions"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                quiz_record.validate(bad)
        graded = vocab.grade(questions, [])
        completed = quiz_record.with_result(record, questions, graded)
        for change in ({"wrong": {"4": ["main"]}}, {"wrong": {"-1": ["main"]}},
                       {"wrong": {"0": "main"}}, {"wrong": {"0": ["main", "main"]}},
                       {"unfamiliar": [True]}, {"unfamiliar": [0, 0]}, {"score": {}}):
            bad = deepcopy(completed)
            bad["result"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                quiz_record.validate(bad)
        completed["result"]["wrong"] = {"0": ["not_an_answer_field"]}
        with self.assertRaisesRegex(ValueError, "unavailable answer field"):
            quiz_record.reconstruct(completed, VAULT)

    def test_missing_and_unselected_chapters_have_useful_errors(self):
        opts, questions = self.vocabulary(4)
        record = quiz_record.make_record("vocabulary", opts, questions, compact=True)
        with patch.object(vocab, "load_vault", return_value={}):
            with self.assertRaisesRegex(ValueError, "original chapter files"):
                quiz_record.reconstruct(record, VAULT)
        record["configuration"]["files"] = ["ch2.md"]
        with self.assertRaisesRegex(ValueError, "Recorded entry.*unavailable"):
            quiz_record.reconstruct(record, VAULT)

    def test_invalid_morphology_choices_and_pair_references_are_rejected(self):
        opts = {"files": ["ch10.md"], **morphology.options({"exhaustive": True})}
        questions = morphology.build_quiz(vocab.load_vault(VAULT)["ch10.md"],
                                          opts, random.Random(4))["questions"]
        record = quiz_record.make_record("morphology", opts, questions, compact=True)
        pair_index = next(i for i, ref in enumerate(record["questions"]) if ref["kind"] == "pair")
        for change in ({"adjective": ""}, {"gender": []}, {"kind": "unknown"}):
            bad = deepcopy(record)
            bad["questions"][pair_index].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                quiz_record.validate(bad)
        bad = deepcopy(record)
        bad["questions"][pair_index]["adjective"] = bad["questions"][pair_index]["entry"]
        with self.assertRaisesRegex(ValueError, "Recorded adjective is unavailable"):
            quiz_record.reconstruct(bad, VAULT)
        pool = [entry for entry in vocab.load_vault(VAULT)["ch6.md"] if entry.headword == "sum"]
        opts = {"files": ["ch6.md"], **morphology.options({"kinds": ["verb"], "voices": ["active"], "count": 1})}
        questions = morphology.build_quiz(pool, opts)["questions"]
        record = quiz_record.make_record("morphology", opts, questions, compact=True)
        record["questions"][0]["voice"] = "passive"
        with self.assertRaisesRegex(ValueError, "Recorded verb configuration is unavailable"):
            quiz_record.reconstruct(record, VAULT)

    def test_legacy_snapshot_does_not_need_chapter_files(self):
        opts, questions = self.vocabulary(4)
        record = quiz_record.make_record("vocabulary", opts, questions)
        with patch.object(vocab, "load_vault", side_effect=AssertionError("Legacy snapshots are self-contained")):
            self.assertEqual(quiz_record.reconstruct(quiz_record.loads(quiz_record.dumps(record)), VAULT), questions)

    def test_restoration_uses_the_supplied_vault_and_current_overrides(self):
        with TemporaryDirectory() as directory:
            vault = Path(directory)
            (vault / "ch.md").write_text("**VERBS**\ncapio, capere, cepi, captum - take\n", encoding="utf-8")
            pool = vocab.load_vault(vault)["ch.md"]
            opts = {"files": ["ch.md"], **morphology.options({"kinds": ["verb"], "voices": ["passive"]})}
            questions = morphology.build_quiz(pool, opts, lexicon=morphology.load_lexicon(vault, include_cache=False),
                                              sources=morphology.table_sources(vault))["questions"]
            record = quiz_record.make_record("morphology", opts, questions, compact=True)
            self.assertEqual(quiz_record.reconstruct(record, vault), questions)
            override = {"version": 1, "verbs": {"capio": {"overrides": {
                "passive": {"infinitive": ["capī", "fixture"]}}}}}
            (vault / "morphology.json").write_text(json.dumps(override), encoding="utf-8")
            restored = quiz_record.reconstruct(record, vault)
            self.assertEqual(restored[0]["fields"][-1]["answer"], "capī / fixture")
            self.assertNotEqual(restored, questions)


if __name__ == "__main__":
    unittest.main()
