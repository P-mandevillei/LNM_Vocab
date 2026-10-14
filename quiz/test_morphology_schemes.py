"""Chapter precedence, independent alternatives and wider cached exercises."""

from copy import deepcopy
import json
from pathlib import Path
import random
from tempfile import TemporaryDirectory
import unittest

import morphology as m
import morphology_answers as a
from morphology_cache import TableSources, empty_cache, table_sources, save_json
import vocab


VAULT = Path(__file__).resolve().parent.parent


class AnswerSchemes(unittest.TestCase):
    def setUp(self):
        self.pool = vocab.load_vault(VAULT)["ch10.md"]

    def quiz(self, head, kind="verb", **settings):
        entry = next(e for e in self.pool if e.headword == head)
        return m.build_quiz([entry], m.options({"kinds": [kind], "count": 1, **settings}),
                            random.Random(1))["questions"][0]

    def fields(self, question):
        return {f["key"]: f for f in question["fields"]}

    def verdict(self, question, key, value):
        result = m.grade([question], [{"fields": {key: value}}])["results"][0]
        return next(f for f in result["fields"] if f["key"] == key)

    def test_chapter_wins_even_when_import_and_rule_agree_against_it(self):
        f = a.cell("test", "Test", chapter=["chapter"], rule=["other"], importer=["other"])
        q = self.quiz("capio", voices=["active"])
        q["fields"] = [f]
        self.assertEqual(self.verdict(q, "test", "chapter")["verdict"], "correct")
        self.assertEqual(self.verdict(q, "test", "other")["verdict"], "wrong")
        self.assertEqual(f["answer"], "chapter")

    def test_real_conflict_is_accepted_from_either_scheme_except_chapter_cell(self):
        q = self.quiz("felix", "adjective", gender="n")
        fields = self.fields(q)
        self.assertEqual(fields["nominative_singular"]["answer"], "felix")
        self.assertTrue(fields["nominative_singular"]["disagreement"])
        self.assertEqual(self.verdict(q, "nominative_singular", "felice")["verdict"], "wrong")
        for key in ("accusative_singular", "vocative_singular"):
            for value in ("fēlīx", "felice"):
                result = self.verdict(q, key, value)
                self.assertNotEqual(result["verdict"], "wrong")
                self.assertTrue(result["disagreement"])
                self.assertEqual(set(result["answer_sources"]), {"rule", "importer"})
        self.assertEqual(fields["genitive_singular"]["answer"], "felicis")

    def test_noun_and_adjective_dictionary_slots_and_number(self):
        for head in ("acer", "celeber", "fortis", "pauci"):
            entry = next(e for e in self.pool if e.headword == head)
            for gender in m.GENDERS:
                q = self.quiz(head, "adjective", gender=gender)
                key = "nominative_plural" if head == "pauci" else "nominative_singular"
                expected = entry.latin_forms["mfn".index(gender)] if len(entry.latin_forms) == 3 else entry.latin_forms[gender == "n"]
                self.assertEqual(self.fields(q)[key]["answer"], expected)
        q = self.quiz("donum", "noun")
        self.assertEqual(self.fields(q)["nominative_singular"]["answer"], "donum")
        self.assertEqual(self.fields(q)["genitive_singular"]["answer"], "doni")

    def test_verb_principal_parts_override_their_exact_slots(self):
        q = self.quiz("capio", voices=["active"], tenses=["present"])
        self.assertEqual(self.fields(q)["p1_singular"]["answer"], "capio")
        self.assertEqual(self.fields(q)["infinitive"]["answer"], "capere")
        q = self.quiz("capio", voices=["active"], tenses=["perfect"])
        self.assertEqual(self.fields(q)["p1_singular"]["answer"], "cepi")
        self.assertEqual(self.fields(q)["p2_singular"]["answer_sources"], {"importer": ["cepisti"]})
        self.assertNotIn("rule", self.fields(q)["infinitive"]["answer_sources"])
        early = vocab.Entry(["amat"], "loves", "verb", "early.md", 1, raw_latin="amat", key="early")
        q = m.build_quiz([early], m.options({"kinds": ["verb"], "voices": ["active"]}))["questions"][0]
        self.assertEqual(q["prompt"], "amō")
        self.assertEqual(self.fields(q)["p3_singular"]["answer_sources"]["chapter"], ["amat"])
        self.assertNotIn("chapter", self.fields(q)["p1_singular"]["answer_sources"])

    def test_multiselect_only_uses_supported_combinations_and_keeps_retest(self):
        opts = m.options({"kinds": ["verb"], "voices": list(m.VOICES),
                          "tenses": list(m.TENSES), "moods": list(m.MOODS), "count": 100})
        qs = m.build_quiz(self.pool, opts, random.Random(9))["questions"]
        configurations = {(q["voice"], q["tense"], q["mood"]) for q in qs}
        self.assertIn(("active", "perfect", "subjunctive"), configurations)
        self.assertIn(("passive", "imperfect", "indicative"), configurations)
        self.assertFalse(any(mood == "subjunctive" and tense.startswith("future") for _, tense, mood in configurations))
        graded = m.grade(qs, [])
        retest = m.retest(qs, graded["missed"], random.Random(1))
        originals = {q["identity"]: q for q in qs}
        for q in retest:
            old = originals[q["identity"]]
            self.assertEqual(q["fields"], old["fields"])
            self.assertEqual((q["voice"], q["tense"], q["mood"]), (old["voice"], old["tense"], old["mood"]))

    def test_missing_principal_part_does_not_shift_the_fourth_part(self):
        entry = vocab.Entry(["capio", "capere", "captum"], "take", "verb", "new.md", 1,
                            raw_latin="capio, capere, ____, captum", key="new")
        q = m.build_quiz([entry], m.options({"kinds": ["verb"], "voices": ["active"],
                                            "tenses": ["perfect"], "count": 1}))["questions"][0]
        field = self.fields(q)["p1_singular"]
        self.assertNotIn("chapter", field["answer_sources"])
        self.assertEqual(field["answer"], "cepi")

    def test_imperative_disables_nonexistent_persons_and_includes_infinitive(self):
        q = self.quiz("capio", voices=["active"], moods=["imperative"])
        f = self.fields(q)
        self.assertTrue(f["p1_singular"]["disabled"])
        self.assertTrue(f["p3_singular"]["disabled"])
        self.assertEqual(f["p2_singular"]["answer"], "cape")
        self.assertEqual(f["p2_plural"]["answer"], "capite")
        self.assertEqual(f["infinitive"]["answer"], "capere")

    def test_unparsed_or_impossible_tables_are_excluded(self):
        for choices in ({"voices": ["passive"], "tenses": ["perfect"]},
                        {"tenses": ["future"], "moods": ["subjunctive"]}):
            result = m.build_quiz(self.pool, m.options({"kinds": ["verb"], **choices}))
            self.assertEqual(result["questions"], [])
            self.assertTrue(result["excluded"])

    def test_quiz_payload_contains_only_one_form_and_no_answers(self):
        q = self.quiz("felix", "adjective", gender="n")
        public = m.public([q])[0]
        self.assertEqual(public["prompt"], "fēlīx")
        serialized = json.dumps(public)
        for hidden in ("fortunate", "felicis", "full_entry", "meaning", "answer_sources", "disagreement", "accepted", "strict"):
            self.assertNotIn(hidden, serialized)
        graded = m.grade([q], [])["results"][0]
        self.assertIn("fortunate", graded["full_entry"])
        self.assertTrue(self.fields(graded)["nominative_singular"]["disagreement"])

    def test_pair_applies_precedence_to_each_component_and_accepts_cross_scheme_order(self):
        pool = [next(e for e in self.pool if e.headword == head) for head in ("donum", "felix")]
        q = m.build_quiz(pool, m.options({"kinds": ["pair"], "count": 1}))["questions"][0]
        for answer in ("donum felice", "felix donum", "dōnum fēlīx"):
            self.assertNotEqual(self.verdict(q, "accusative_singular", answer)["verdict"], "wrong")
        self.assertEqual(self.verdict(q, "nominative_singular", "donum felice")["verdict"], "wrong")
        self.assertTrue(self.verdict(q, "accusative_singular", "donum felice")["disagreement"])

    def test_cached_word_without_implemented_rules_uses_importer_only(self):
        # No third-declension rule metadata; a complete independent cache
        # provides the table. Ready imports need no legacy-schema approval.
        entry = vocab.Entry(["fixture", "fixturis"], "fixture", "noun", "new.md", 1,
                            gender="m.", raw_latin="fixture, fixturis, m.", key="new")
        data = empty_cache()
        cells = {}
        for case in m.CASES:
            for number in m.NUMBERS:
                features = dict(pos="noun", case=case, number=number)
                key = "|".join(f"{k}={v}" for k, v in sorted(features.items()))
                cells[key] = {"features": features, "forms": [f"{case}{number}"],
                              "source_forms": [f"{case}{number}"], "status": "available"}
        data["entries"]["fixture"] = {"status": "ready", "review_status": "unreviewed",
            "request": {"pos": "noun", "forms": entry.latin_forms, "genders": ["m"], "number": None},
            "candidate": {"cells": cells}}
        sources = TableSources(data)
        q = m.build_quiz([entry], m.options({"kinds": ["noun"], "count": 1}), sources=sources)["questions"][0]
        f = self.fields(q)
        self.assertEqual(f["genitive_singular"]["answer"], "fixturis")
        self.assertEqual(f["dative_plural"]["answer_sources"], {"importer": ["dativeplural"]})
        self.assertFalse(f["dative_plural"]["disagreement"])
        self.assertEqual(self.verdict(q, "dative_plural", "dativeplural")["verdict"], "correct")

    def test_cache_stays_unchanged_and_reloads_after_update(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "morphology_cache.json"
            data = deepcopy(empty_cache())
            save_json(path, data)
            before = (path.read_bytes(), path.stat().st_mtime_ns)
            first = table_sources(directory)
            self.assertIs(table_sources(directory), first)
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            data["skipped"]["new"] = {"reason": "test"}
            save_json(path, data)
            self.assertIsNot(table_sources(directory), first)

    def test_unclassified_verb_can_use_a_complete_cached_passive(self):
        entry = vocab.Entry(["fixtureo", "fixturere"], "fixture", "verb", "new.md", 1,
                            raw_latin="fixtureo, fixturere", key="new")
        data = empty_cache()
        cells = {}
        for number in m.NUMBERS:
            for person in range(1, 4):
                features = dict(pos="verb", mood="indicative", voice="passive", tense="present", person=person, number=number)
                key = "|".join(f"{k}={v}" for k, v in sorted(features.items()))
                cells[key] = {"features": features, "forms": [f"form{person}{number}"]}
        features = dict(pos="verb", form="infinitive", voice="passive", tense="present")
        cells["|".join(f"{k}={v}" for k, v in sorted(features.items()))] = {"features": features, "forms": ["fixturi"]}
        data["entries"]["fixture"] = {"status": "ready", "review_status": "unreviewed",
            "request": {"pos": "verb", "forms": entry.latin_forms, "passive": False}, "candidate": {"cells": cells}}
        q = m.build_quiz([entry], m.options({"kinds": ["verb"], "voices": ["passive"], "count": 1}),
                         sources=TableSources(data))["questions"][0]
        self.assertTrue(all(not f["disabled"] and set(f["answer_sources"]) == {"importer"} for f in q["fields"]))

    def test_selection_validation_and_legacy_voice_api(self):
        self.assertEqual(m.options({"voice": "passive"})["voices"], ["passive"])
        for name in ("voices", "tenses", "moods"):
            for invalid in ([], ["invalid"], "present"):
                with self.assertRaises(ValueError):
                    m.options({name: invalid})
        self.assertEqual(m.options({"kinds": ["noun"], "voices": []})["voices"], [])


if __name__ == "__main__":
    unittest.main()
