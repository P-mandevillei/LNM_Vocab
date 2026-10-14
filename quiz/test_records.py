"""Regression coverage for portable records and the three retest selections."""

from copy import deepcopy
from http.client import HTTPConnection
import json
from pathlib import Path
import random
import threading
import unittest
from unittest.mock import patch

import morphology
import quiz_record
import server
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


class RecordHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.Server(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def request(self, path, payload, expected=200):
        conn = HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=10)
        try:
            conn.request("POST", path, body=json.dumps(payload), headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            body = response.read()
            self.assertEqual(response.status, expected, body)
            return json.loads(body)
        finally:
            conn.close()

    def test_records_replay_after_restart_without_chapters_and_keep_keys_private(self):
        for kind, path in (("vocabulary", "/api/quiz"), ("morphology", "/api/morphology/quiz")):
            with self.subTest(kind=kind):
                data = self.request(path, {"files": ["ch10.md"], "count": 4})
                record = self.request("/api/record", {"id": data["id"]})
                questions = deepcopy(server.QUIZZES[data["id"]]["questions"])
                server.QUIZZES.clear()
                with patch.object(vocab, "load_vault", side_effect=AssertionError("Replay must use the record")):
                    replay = self.request("/api/record/restore", {"record": record})
                    self.assertEqual(replay["questions"], data["questions"])
                    self.assertEqual(server.QUIZZES[replay["id"]]["questions"], questions)
                    for question in replay["questions"]:
                        self.assertNotIn("accepted", question)
                        self.assertNotIn("answer", question)
                        for field in question["fields"]:
                            self.assertNotIn("accepted", field)
                            self.assertNotIn("answer", field)
                    graded = self.request("/api/grade", {"id": replay["id"], "answers": answers_for(kind, questions)})
                    self.assertEqual(graded["score"]["missed"], 0)
                    self.assertFalse(any(r["unfamiliar"] for r in graded["results"]))

    def test_each_retest_selection_and_record_use_original_snapshots(self):
        for kind, path in (("vocabulary", "/api/quiz"), ("morphology", "/api/morphology/quiz")):
            with self.subTest(kind=kind):
                data = self.request(path, {"files": ["ch10.md"], "count": 4, "mode": "la_to_en"})
                qs = server.QUIZZES[data["id"]]["questions"]
                answers = answers_for(kind, qs)
                answers[0]["unfamiliar"] = True
                answers[3]["unfamiliar"] = True
                for index in (1, 3):
                    if kind == "vocabulary":
                        answers[index]["main"] = "wrong"
                    else:
                        field = next(f for f in qs[index]["fields"] if not f["disabled"])
                        answers[index]["fields"][field["key"]] = "wrong"
                graded = self.request("/api/grade", {"id": data["id"], "answers": answers})
                self.assertEqual(graded["retest_counts"], {"wrong": 2, "unfamiliar": 2, "combined": 3})
                for selection, expected in (("wrong", [1, 3]), ("unfamiliar", [0, 3]), ("combined", [0, 1, 3])):
                    with patch.object(vocab, "load_vault", side_effect=AssertionError("Retest must use snapshots")):
                        retest = self.request("/api/retest", {"id": data["id"], "selection": selection})
                    record = self.request("/api/record", {"id": retest["id"]})
                    self.assertTrue(record["retest"])
                    self.assertEqual(record["configuration"]["retest_selection"], selection)
                    identity = "identity" if kind == "morphology" else "entry_key"
                    expected_qs = {qs[i][identity]: {**qs[i], "index": 0} for i in expected}
                    self.assertEqual({q[identity] for q in record["questions"]}, set(expected_qs))
                    for q in record["questions"]:
                        self.assertEqual({**q, "index": 0}, expected_qs[q[identity]])
                        self.assertNotIn("unfamiliar", q)
                    replay = self.request("/api/record/restore", {"record": record})
                    self.assertEqual(replay["questions"], retest["questions"])
                    graded_retest = self.request("/api/grade", {"id": replay["id"], "answers": answers_for(kind, record["questions"])})
                    self.assertEqual(graded_retest["score"]["missed"], 0)
                    self.assertEqual(graded_retest["retest_counts"]["unfamiliar"], 0)

    def test_invalid_records_and_selections_do_not_create_quizzes(self):
        before = len(server.QUIZZES)
        self.request("/api/record/restore", {"record": {}}, expected=400)
        self.request("/api/record", {"id": "expired"}, expected=400)
        self.assertEqual(len(server.QUIZZES), before)
        data = self.request("/api/quiz", {"files": ["ch1.md"], "count": 1})
        self.request("/api/grade", {"id": data["id"], "answers": []})
        self.request("/api/retest", {"id": data["id"], "selection": "unfamiliar"}, expected=400)
        self.request("/api/retest", {"id": data["id"], "selection": "invalid"}, expected=400)


if __name__ == "__main__":
    unittest.main()
