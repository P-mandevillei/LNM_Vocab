"""Live-response parser fixtures, incremental state and legacy-schema safety."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import URLError

import collatinus as p
import import_morphology as importer
import morphology as m
from morphology_cache import CacheError, cache_lock, legacy_record, load_cache, lookup, save_json
import morphology_cache
import vocab


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "collatinus"


def fixture(word):
    return (FIXTURES / f"{word}.html").read_bytes()


def noun_response(head):
    stem = head[:-1]
    sg = [head, head, stem + "am", stem + "ae", stem + "ae", stem + "a"]
    pl = [stem + "ae", stem + "ae", stem + "as", stem + "arum", stem + "is", stem + "is"]
    rows = "".join(f"<tr><td>{case}</td><td>{s}</td><td>{v}</td></tr>"
                   for case, s, v in zip(p.CASES, sg, pl))
    return (f'<h4><a href="#{head}">{head}</a> {head}, ae, f.</h4><a name="{head}"></a>'
            '<table><tr><td>cas</td><td>singulier</td><td>pluriel</td></tr>' + rows + '</table>').encode()


class FakeClient:
    endpoint = "fixture://collatinus"

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def fetch(self, word):
        self.calls.append(word)
        response = self.responses.get(word, noun_response(word))
        if isinstance(response, BaseException):
            raise response
        return response


class ParserFixtures(unittest.TestCase):
    def test_present_persons_infinitives_and_future_coverage(self):
        candidate = p.parse_response(fixture("capio"))[0]
        for index, expected in enumerate("capio capis capit capimus capitis capiunt".split()):
            cell = lookup(candidate, pos="verb", mood="indicative", tense="present", voice="active",
                          person=index % 3 + 1, number="singular" if index < 3 else "plural")
            self.assertEqual(cell["forms"], [expected])
        self.assertEqual(lookup(candidate, pos="verb", form="infinitive", tense="present", voice="passive")["forms"], ["capi"])
        self.assertEqual(set(lookup(candidate, pos="verb", mood="indicative", tense="present", voice="passive",
                                   person=2, number="singular")["forms"]), {"caperis", "capere"})
        self.assertEqual(lookup(candidate, pos="verb", mood="indicative", tense="future", voice="active",
                                person=1, number="singular")["forms"], ["capiam"])
        self.assertIsNone(lookup(candidate, pos="verb", mood="indicative", tense="perfect", voice="passive",
                                 person=2, number="singular"))
        self.assertEqual(len(candidate["unparsed"]), 2)
        self.assertEqual(len(candidate["cells"]), 255)

    def test_provider_conflict_is_preserved_not_corrected_from_legacy(self):
        candidate = p.parse_response(fixture("felix"))[0]
        cell = lookup(candidate, pos="adjective", degree="positive", case="nominative", number="singular", gender="n")
        self.assertEqual(cell["forms"], ["felice"])
        self.assertEqual(cell["source_forms"], ["fēlīcĕ"])
        self.assertEqual(len(candidate["cells"]), 108)

    def test_plural_adjective_resolves_to_adjective_not_same_spelling_noun(self):
        candidates = p.parse_response(fixture("pauci"))
        request = {"pos": "adjective", "forms": ["paucī", "paucae", "pauca"], "number": "pl"}
        candidate = importer.resolve(candidates, request)
        self.assertEqual(candidate["id"], "paucus")
        self.assertEqual(lookup(candidate, pos="adjective", degree="positive", case="nominative",
                                number="plural", gender="n")["forms"], ["pauca"])
        legacy = legacy_record({**request, "genders": ["m", "f", "n"]}, candidate)
        self.assertEqual(len(legacy["overrides"]["n"]), 6)
        self.assertNotIn("nominative_singular", legacy["overrides"]["n"])

    def test_noun_case_order_and_variants(self):
        candidate = p.parse_response(fixture("deus"))[0]
        self.assertEqual(set(lookup(candidate, pos="noun", case="nominative", number="plural")["forms"]),
                         {"dei", "dii", "di"})
        self.assertEqual(set(lookup(candidate, pos="noun", case="genitive", number="plural")["forms"]),
                         {"deorum", "deum"})

    def test_html_error_is_not_cached_as_a_successful_empty_table(self):
        self.assertEqual(p.parse_response(b""), [])
        with self.assertRaises(p.ProviderError):
            p.parse_response(b"<html>Service unavailable</html>")

    def test_dictionary_resolution_does_not_use_arbitrary_inflected_forms(self):
        candidate = p.parse_response(fixture("deus"))[0]
        self.assertIsNone(importer.resolve([candidate], {"pos": "noun", "forms": ["deo", "dei"]}))
        other = deepcopy(candidate)
        other["id"] = "deus2"
        other["cells"][p.feature_key({"pos": "noun", "case": "genitive", "number": "singular"})]["forms"] = ["different"]
        resolved = importer.resolve([other, candidate], {"pos": "noun", "forms": ["deus", "dei"]})
        self.assertEqual(resolved["id"], "deus")

    def test_multiple_headword_spellings_and_consonantal_j(self):
        candidate = p.parse_response(fixture("capio"))[0]
        # The source's alternate dictionary headwords are comma-separated.
        candidate["headword"] = "capio,other"
        self.assertEqual(importer.resolve([candidate], {"pos": "verb", "forms": ["capio", "capere"]})["id"], "capio")
        self.assertEqual(p.dictionary_spelling("jūstus"), "iustus")

    def test_quantity_distinct_homographs_are_not_merged(self):
        first = p.parse_response(fixture("deus"))[0]
        second = deepcopy(first)
        second["id"] = "different_lexeme"
        lookup(second, pos="noun", case="nominative", number="singular")["source_forms"] = ["dēus"]
        self.assertIsNone(importer.resolve([first, second], {"pos": "noun", "forms": ["deus", "dei"]}))


class IncrementalImport(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name)
        self.cache = self.vault / "morphology_cache.json"

    def chapter(self, text, name="ch10.md"):
        (self.vault / name).write_text(text, encoding="utf-8")

    def run_import(self, client, **kwargs):
        return importer.import_tables(self.vault, self.cache, client=client, progress=lambda text: None, **kwargs)

    def test_unchanged_update_has_zero_calls_and_identical_cache(self):
        self.chapter("**VERBS**\ncapio, capere, cepi, captum - take\n")
        first = self.run_import(FakeClient({"capio": fixture("capio")}))
        self.assertEqual(first["calls"], 1)
        original, modified = self.cache.read_bytes(), self.cache.stat().st_mtime_ns
        client = FakeClient()
        again = self.run_import(client)
        self.assertEqual(again["calls"], 0)
        self.assertEqual(client.calls, [])
        self.assertEqual(self.cache.read_bytes(), original)
        self.assertEqual(self.cache.stat().st_mtime_ns, modified)
        self.chapter("**VERBS**\ncapio, capere, cepi, captum - a changed English gloss\n", "ch11.md")
        self.assertEqual(self.run_import(client)["calls"], 0)
        self.assertEqual(self.cache.read_bytes(), original)

    def test_ten_new_lemmas_only_make_ten_requests_and_duplicates_reuse(self):
        self.chapter("**NOUNS**\nrosa, rosae, f. - rose\n")
        self.run_import(FakeClient())
        words = "porta villa insula stella luna silva cura vita via aqua".split()
        self.chapter("**NOUNS**\nrosa, rosae, f. - rose\n" + "\n".join(f"{w}, {w[:-1]}ae, f. - fixture" for w in words))
        client = FakeClient()
        result = self.run_import(client)
        self.assertEqual(result["calls"], 10)
        self.assertEqual(set(client.calls), set(words))
        self.assertEqual(len(load_cache(self.cache)["entries"]), 11)

    def test_verb_dictionary_listing_lengths_reuse_one_acquisition(self):
        self.chapter("**VERBS**\nrapio, rapere, rapui, raptum - seize\n")
        source = fixture("capio").decode().replace("capio", "rapio").replace("căp", "răp").replace("cāp", "rāp").replace("cēp", "răpu").encode()
        client = FakeClient({"rapio": source})
        self.assertEqual(self.run_import(client)["calls"], 1)
        self.chapter("**VERBS**\nrapio, rapere - seize\n", "ch11.md")
        self.assertEqual(self.run_import(client)["calls"], 0)
        records = load_cache(self.cache)["entries"]
        self.assertEqual(len(records), 1)
        self.assertEqual(next(iter(records.values()))["request"]["principal_parts"], ["rapio", "rapere", "rapui", "raptum"])

    def test_negative_cache_and_explicit_retry(self):
        self.chapter("**NOUNS**\nrosa, rosae, f. - rose\n")
        self.assertEqual(self.run_import(FakeClient({"rosa": b""}))["not_found"], 1)
        client = FakeClient()
        self.assertEqual(self.run_import(client)["calls"], 0)
        self.assertEqual(self.run_import(client, retry_missing=True)["calls"], 1)
        self.assertEqual(next(iter(load_cache(self.cache)["entries"].values()))["status"], "ready")

    def test_failed_refresh_retains_validated_answers_and_approval(self):
        self.chapter("**NOUNS**\nrosa, rosae, f. - rose\n")
        self.run_import(FakeClient())
        data = load_cache(self.cache)
        key = next(iter(data["entries"]))
        data["entries"][key]["review_status"] = "approved"
        save_json(self.cache, data)
        previous = deepcopy(data["entries"][key]["candidate"])
        stats = self.run_import(FakeClient({"rosa": URLError("fixture timeout")}), refresh=["rosa"])
        self.assertEqual(stats["errors"], 1)
        retained = load_cache(self.cache)["entries"][key]
        self.assertEqual(retained["candidate"], previous)
        self.assertEqual(retained["review_status"], "approved")
        self.assertIn("last_refresh_error", retained)

    def test_empty_refresh_also_retains_the_previous_ready_table(self):
        self.chapter("**NOUNS**\nrosa, rosae, f. - rose\n")
        self.run_import(FakeClient())
        original = next(iter(load_cache(self.cache)["entries"].values()))["candidate"]
        self.run_import(FakeClient({"rosa": b""}), refresh=["rosa"])
        record = next(iter(load_cache(self.cache)["entries"].values()))
        self.assertEqual(record["status"], "ready")
        self.assertEqual(record["candidate"], original)
        self.assertEqual(record["last_refresh_error"]["status"], "not_found")

    def test_changed_refresh_waits_for_review_before_replacing_approved_answers(self):
        self.chapter("**NOUNS**\nrosa, rosae, f. - rose\n")
        self.run_import(FakeClient())
        data = load_cache(self.cache)
        key = next(iter(data["entries"]))
        importer.approve_entry(data, key)
        save_json(self.cache, data)
        changed = noun_response("rosa").replace(b"rosam", b"rosom")
        self.run_import(FakeClient({"rosa": changed}), refresh=["rosa"])
        data = load_cache(self.cache)
        record = data["entries"][key]
        self.assertEqual(lookup(record["candidate"], pos="noun", case="accusative", number="singular")["forms"], ["rosam"])
        self.assertIn("pending_refresh", record)
        importer.approve_entry(data, key)
        self.assertEqual(lookup(data["entries"][key]["candidate"], pos="noun", case="accusative", number="singular")["forms"], ["rosom"])

    def test_interrupted_import_resumes_completed_records(self):
        self.chapter("**NOUNS**\naqua, aquae, f. - water\nrosa, rosae, f. - rose\n")
        with self.assertRaises(KeyboardInterrupt):
            self.run_import(FakeClient({"rosa": KeyboardInterrupt()}))
        self.assertEqual(len(load_cache(self.cache)["entries"]), 1)
        client = FakeClient()
        self.assertEqual(self.run_import(client)["calls"], 1)
        self.assertEqual(client.calls, ["rosa"])

    def test_reparse_and_offline_comparison_make_no_network_calls(self):
        self.chapter("**ADJECTIVES**\nfelix, felicis - happy\n")
        self.run_import(FakeClient({"felix": fixture("felix")}))
        client = FakeClient()
        result = self.run_import(client, offline=True, reparse=True)
        self.assertEqual(result["calls"], 0)
        self.assertEqual(client.calls, [])
        report = importer.compare(self.vault, self.cache)
        self.assertEqual(report["summary"]["conflict"], 3)
        self.assertEqual(report["summary"]["missing"], 0)
        self.assertEqual(report["summary"]["reference_cells"], 36)

    def test_approved_cache_is_offline_fallback_and_old_definitions_win(self):
        self.chapter("**NOUNS**\nrosa, rosae, f. - rose\ndeus, dei, m. - god\n")
        self.run_import(FakeClient({"deus": fixture("deus")}))
        data = load_cache(self.cache)
        for record in data["entries"].values():
            record["review_status"] = "approved"
            if record["request"]["query"] == "deus":
                field = lookup(record["candidate"], pos="noun", case="nominative", number="singular")
                field["forms"] = ["incorrect"]
        save_json(self.cache, data)
        lexicon = m.load_lexicon(self.vault)
        rosa = vocab.parse_file(self.vault / "ch10.md", self.vault)[0]
        self.assertEqual(m.noun_model(rosa, lexicon).declension, 0)
        self.assertFalse(m.noun_model(rosa, lexicon).quantities_known)
        self.assertEqual(m.decline(lexicon.nouns["deus"], "m")["nominative", "singular"], ["deus"])
        self.assertNotIn("rosa", m.load_lexicon(self.vault, include_cache=False).nouns)
        # A normal v1 rule declaration also replaces a cached custom paradigm.
        (self.vault / "morphology.json").write_text(json.dumps({"version": 1, "nouns": {"rosa": {"declension": 1}}}), encoding="utf-8")
        self.assertEqual(m.noun_model(rosa, m.load_lexicon(self.vault)).declension, 1)

    def test_unapproved_cache_does_not_change_runtime_or_old_schema(self):
        self.chapter("**ADJECTIVES**\nfelix, felicis - happy\n")
        self.run_import(FakeClient({"felix": fixture("felix")}))
        lexicon = m.load_lexicon(self.vault)
        self.assertEqual(m.decline(lexicon.adjectives["felix"], "n")["nominative", "singular"], ["fēlīx"])

    def test_reviewed_new_third_declension_word_is_graded_and_retested_offline(self):
        self.chapter("**NOUNS**\nignis, ignis, m. - fire\n")
        rows = "".join(f"<tr><td>{case}</td><td>{sg}</td><td>{pl}</td></tr>" for case, sg, pl in zip(
            p.CASES, "ignis ignis ignem ignis igni igne".split(), "ignes ignes ignes ignium ignibus ignibus".split()))
        source = ('<h4><a href="#ignis">ignis</a> ignis, is, m.</h4><a name="ignis"></a>'
                  '<table><tr><td>cas</td><td>singulier</td><td>pluriel</td></tr>' + rows + '</table>').encode()
        self.run_import(FakeClient({"ignis": source}))
        word = vocab.parse_file(self.vault / "ch10.md", self.vault)[0]
        with self.assertRaises(m.Unavailable):
            m.noun_model(word, m.load_lexicon(self.vault))
        data = load_cache(self.cache)
        importer.approve_entry(data, next(iter(data["entries"])))
        save_json(self.cache, data)
        with patch.object(p.CollatinusClient, "fetch", side_effect=AssertionError("Runtime API call")):
            lexicon = m.load_lexicon(self.vault)
            questions = m.build_quiz([word], m.options({"kinds": ["noun"], "count": 1}), lexicon=lexicon)["questions"]
            answers = [{"fields": {f["key"]: f["answer"].split(" / ")[0] for f in questions[0]["fields"]}}]
            answers[0]["fields"]["genitive_plural"] = "wrong"
            grade = m.grade(questions, answers)
            self.assertEqual(grade["score"]["missed"], 1)
            retest = m.retest(questions, grade["missed"])
            self.assertEqual(retest[0]["fields"], questions[0]["fields"])
            answers[0]["fields"]["genitive_plural"] = "ignium"
            self.assertEqual(m.grade(retest, answers)["score"]["missed"], 0)

    def test_atomic_replace_retries_a_transient_windows_file_lock(self):
        actual_replace = morphology_cache.os.replace
        calls = []
        def replace(source, target):
            calls.append(target)
            if len(calls) < 3:
                raise PermissionError("fixture sync lock")
            actual_replace(source, target)
        with patch.object(morphology_cache.os, "replace", replace), patch.object(morphology_cache.time, "sleep"):
            self.assertTrue(save_json(self.cache, {"fixture": True}))
        self.assertEqual(len(calls), 3)
        self.assertEqual(json.loads(self.cache.read_text()), {"fixture": True})

    def test_dry_run_and_single_writer_lock(self):
        self.chapter("**NOUNS**\nrosa, rosae, f. - rose\n")
        client = FakeClient()
        self.assertEqual(self.run_import(client, dry_run=True)["pending"], 1)
        self.assertFalse(self.cache.exists())
        self.assertEqual(client.calls, [])
        with cache_lock(self.cache):
            with self.assertRaises(CacheError):
                with cache_lock(self.cache):
                    self.fail("Second writer was allowed")
        self.assertFalse(Path(str(self.cache) + ".lock").exists())


if __name__ == '__main__':
    unittest.main()
