"""Future vocabulary, user-defined exceptions and live answer-key reloads."""

from http.client import HTTPConnection
import json
from pathlib import Path
import random
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

import morphology as m
from morphology_data import LexiconError
import server
import vocab


def word(forms, pos="noun", gender=None):
    return vocab.Entry(forms, "reference fixture", pos, "ch10.md", 1,
                       gender=gender, raw_latin=", ".join(forms),
                       key=f"ch10.md:{pos}:{forms[0]}")


def fero_definition():
    keys = ["p1_singular", "p2_singular", "p3_singular", "p1_plural", "p2_plural", "p3_plural", "infinitive"]
    return {"headword": "ferō", "infinitive": "ferre", "conjugation": "custom", "passive": True,
            "paradigms": {
                "active": dict(zip(keys, "ferō fers fert ferimus fertis ferunt ferre".split())),
                "passive": {**dict(zip(keys, "feror ferris fertur ferimur feriminī feruntur ferrī".split())),
                            "p2_singular": ["ferris", "ferre"]}}}


class ExtensibleAnswerKeys(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name)

    def write(self, **categories):
        (self.vault / "morphology.json").write_text(
            json.dumps({"version": 1, **categories}, ensure_ascii=False), encoding="utf-8")

    def lexicon(self):
        return m.load_lexicon(self.vault)

    def decline(self, entry, gender=None):
        model = (m.adjective_model if entry.pos == "adjective" else m.noun_model)(entry, self.lexicon())
        return m.decline(model, gender or model.genders[0])

    def assertTable(self, entry, sg, pl):
        table = self.decline(entry)
        self.assertEqual([table[c, "singular"][0] for c in m.CASES], sg.split())
        self.assertEqual([table[c, "plural"][0] for c in m.CASES], pl.split())

    def test_new_regular_words_work_without_lexical_definitions(self):
        self.assertTable(word(["rosa", "rosae"], gender="f."),
                         "rosa rosae rosae rosam rosā rosa", "rosae rosārum rosīs rosās rosīs rosae")
        self.assertTable(word(["manus", "manūs"], gender="f."),
                         "manus manūs manuī manum manū manus", "manūs manuum manibus manūs manibus manūs")
        self.assertTable(word(["cornū", "cornūs"], gender="n."),
                         "cornū cornūs cornū cornū cornū cornū", "cornua cornuum cornibus cornua cornibus cornua")
        self.assertTable(word(["rēs", "reī"], gender="f."),
                         "rēs reī reī rem rē rēs", "rēs rērum rēbus rēs rēbus rēs")
        self.assertTable(word(["diēs", "diēī"], gender="m."),
                         "diēs diēī diēī diem diē diēs", "diēs diērum diēbus diēs diēbus diēs")
        self.assertEqual(len(self.decline(word(["spēs", "speī"], gender="f."))), 6)

    def test_third_declension_adjectives_and_agreement(self):
        adjective = word(["fortis", "forte"], "adjective")
        neuter = self.decline(adjective, "n")
        self.assertEqual([neuter[c, "singular"][0] for c in m.CASES],
                         "forte fortis fortī forte fortī forte".split())
        self.assertEqual([neuter[c, "plural"][0] for c in m.CASES],
                         "fortia fortium fortibus fortia fortibus fortia".split())
        masculine = self.decline(adjective, "m")
        self.assertEqual(masculine["accusative", "plural"], ["fortēs", "fortīs"])
        acer = self.decline(word(["ācer", "ācris", "ācre"], "adjective"), "m")
        self.assertEqual(acer["genitive", "singular"], ["ācris"])
        q = m.build_quiz([word(["cornū", "cornūs"], gender="n."), adjective],
                         m.options({"kinds": ["pair"], "count": 1}),
                         random.Random(1), self.lexicon())["questions"][0]
        self.assertEqual(next(f["answer"] for f in q["fields"] if f["key"] == "nominative_plural"), "cornua fortia")

    def test_minimal_metadata_enables_new_ambiguous_words(self):
        ignis = word(["ignis", "ignis"], gender="m.")
        with self.assertRaises(m.Unavailable):
            m.noun_model(ignis, self.lexicon())
        self.write(nouns={"ignis": {"declension": 3, "i_stem": True}},
                   adjectives={"felix": {"declension": 3, "i_stem": True}},
                   verbs={"lego": {"conjugation": 3, "passive": True}})
        self.assertEqual(self.decline(ignis)["genitive", "plural"], ["ignium"])
        felix = self.decline(word(["fēlīx", "fēlīcis"], "adjective"), "n")
        self.assertEqual(felix["nominative", "singular"], ["fēlīx"])
        self.assertEqual(felix["nominative", "plural"], ["fēlīcia"])
        forms, inf = m.conjugate(m.verb_model(word(["lego", "legere"], "verb"), self.lexicon()), "passive")
        self.assertEqual([f[0] for f in forms], "legor legeris legitur legimur legiminī leguntur".split())
        self.assertEqual(inf, ["legī"])

    def test_first_second_adjective_pronominal_exception(self):
        self.write(adjectives={"unus": {"declension": 2, "pronominal": True}})
        adjective = word(["ūnus", "ūna", "ūnum"], "adjective")
        for gender in m.GENDERS:
            forms = self.decline(adjective, gender)
            self.assertEqual(forms["genitive", "singular"], ["ūnīus"])
            self.assertEqual(forms["dative", "singular"], ["ūnī"])

    def test_regular_verb_classes_and_passive_metadata(self):
        self.write(verbs={"capio": {"conjugation": "3io", "passive": True},
                          "moneo": {"conjugation": 2, "passive": True}})
        model = m.verb_model(word(["capiō", "capere"], "verb"), self.lexicon())
        active, inf = m.conjugate(model, "active")
        self.assertEqual([f[0] for f in active], "capiō capis capit capimus capitis capiunt".split())
        self.assertEqual(inf, ["capere"])
        passive, inf = m.conjugate(model, "passive")
        self.assertEqual([f[0] for f in passive], "capior caperis capitur capimur capiminī capiuntur".split())
        self.assertEqual(inf, ["capī"])
        model = m.verb_model(word(["moneo", "monere"], "verb"), self.lexicon())
        self.assertEqual(m.conjugate(model, "active")[1], ["monēre"])
        self.assertEqual(m.conjugate(model, "passive")[1], ["monērī"])

    def test_user_exceptions_merge_with_bundled_data_and_reload(self):
        self.write(nouns={"filia": {"overrides": {"dative_plural": ["fīliīs", "fīliābus"]}}})
        original = self.lexicon()
        forms = self.decline(word(["filia", "filiae"], gender="f."))
        self.assertEqual(forms["dative", "plural"], ["fīliīs", "fīliābus"])
        self.assertEqual(forms["ablative", "plural"], ["fīliābus", "fīliīs"])
        self.write(nouns={"filia": {"overrides": {"dative_plural": "fīliābus"}}})
        self.assertEqual(self.decline(word(["filia", "filiae"], gender="f."))["dative", "plural"], ["fīliābus"])
        self.assertEqual(m.decline(original.nouns["filia"], "f")["dative", "plural"], ["fīliīs", "fīliābus"])

    def test_complete_custom_tables_for_new_irregular_words(self):
        sg = "deus deī deō deum deō deus".split()
        pl = "dī deōrum dīs deōs dīs dī".split()
        table = {f"{case}_{number}": values[i] for number, values in zip(m.NUMBERS, (sg, pl))
                 for i, case in enumerate(m.CASES)}
        table["nominative_plural"] = ["dī", "diī", "deī"]
        indeclinable = {key: "frūgī" for key in table}
        self.write(nouns={"deus": {"declension": "custom", "gender": "m", "overrides": table}},
                   adjectives={"frugi": {"declension": "custom", "overrides": {g: indeclinable for g in m.GENDERS}}},
                   verbs={"fero": fero_definition()})
        forms = self.decline(word(["deus"], gender="m."))
        self.assertEqual(forms["vocative", "singular"], ["deus"])
        self.assertEqual(forms["nominative", "plural"], ["dī", "diī", "deī"])
        for gender in m.GENDERS:
            self.assertEqual(set(tuple(v) for v in self.decline(word(["frūgī"], "adjective"), gender).values()), {("frūgī",)})
        model = m.verb_model(word(["ferō", "ferre"], "verb"), self.lexicon())
        passive, infinitive = m.conjugate(model, "passive")
        self.assertEqual(passive[1], ["ferris", "ferre"])
        self.assertEqual(infinitive, ["ferrī"])
        data = m.build_quiz([word(["ferō", "ferre"], "verb")], m.options({"kinds": ["verb"], "voice": "passive", "count": 1}),
                            random.Random(1), self.lexicon())
        answers = [{"fields": {f["key"]: f["answer"].split(" / ")[0] for f in data["questions"][0]["fields"]}}]
        answers[0]["fields"]["p2_singular"] = "ferre"
        self.assertEqual(m.grade(data["questions"], answers)["score"]["missed"], 0)

    def test_validation_identifies_bad_definitions(self):
        cases = [
            {"nouns": {"ignis": {"declension": 9}}},
            {"nouns": {"ignis": {"declension": 3, "i_stem": "yes"}}},
            {"nouns": {"ignis": {"declension": 3, "overrides": {"genetive_plural": "ignium"}}}},
            {"nouns": {"ignis": {"declension": 3, "forms": ["aqua", "aquae"]}}},
            {"nouns": {"ignis": {"declension": "custom", "overrides": {
                f"{case}_{number}": None for case in m.CASES for number in m.NUMBERS}}}},
            {"adjectives": {"fortis": {"declension": "custom", "overrides": {}}}},
            {"adjectives": {"fortis": {"declension": 3, "pronominal": True}}},
            {"verbs": {"fero": {"conjugation": "custom", "paradigms": {"active": {"infinitive": "ferre"}}}}},
            {"verbs": {"lego": {"conjugation": 3, "passive": "yes"}}},
            {"verbs": {"lego": {"conjugation": 3, "overrides": {"active": {"infinitive": None}}}}},
            {"verbs": {"lego": {"conjugation": 3, "aliases": ["legit"]}}},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.write(**case)
                with self.assertRaisesRegex(LexiconError, "morphology.json"):
                    self.lexicon()
        (self.vault / "morphology.json").write_text('{"version":1,"nouns":{},"nouns":{}}', encoding="utf-8")
        with self.assertRaisesRegex(LexiconError, "duplicate JSON key"):
            self.lexicon()

    def test_live_http_reload_and_original_quiz_key(self):
        (self.vault / "ch10.md").write_text("**NOUNS**\nignis, ignis, m. - fire\n", encoding="utf-8")
        httpd = server.Server(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def request(path, body=None, status=200):
            connection = HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
            try:
                connection.request("GET" if body is None else "POST", path,
                                   None if body is None else json.dumps(body),
                                   {} if body is None else {"Content-Type": "application/json"})
                response = connection.getresponse()
                data = json.loads(response.read())
                self.assertEqual(response.status, status, data)
                return data
            finally:
                connection.close()

        try:
            with patch.object(server, "VAULT", self.vault):
                opts = {"files": ["ch10.md"], "kinds": ["noun"], "count": 1}
                self.assertEqual(request('/api/morphology/pool', opts)["pool"], 0)
                self.write(nouns={"ignis": {"declension": 3, "i_stem": True}})
                self.assertEqual(request('/api/morphology/pool', opts)["pool"], 1)
                quiz = request('/api/morphology/quiz', opts)
                self.write(nouns={"ignis": {"declension": 3, "i_stem": True,
                                            "overrides": {"genitive_plural": ["ignium", "ignum"]}}})
                newer = request('/api/morphology/quiz', opts)
                older_grade = request('/api/grade', {"id": quiz["id"], "answers": []})
                newer_grade = request('/api/grade', {"id": newer["id"], "answers": []})
                old_forms, new_forms = older_grade["results"][0]["fields"], newer_grade["results"][0]["fields"]
                self.assertEqual(next(f["answer"] for f in old_forms if f["key"] == "genitive_plural"), "ignium")
                self.assertEqual(next(f["answer"] for f in new_forms if f["key"] == "genitive_plural"), "ignium / ignum")
                retest = request('/api/retest', {"id": quiz["id"]})
                retest_grade = request('/api/grade', {"id": retest["id"], "answers": []})
                self.assertEqual(retest_grade["results"][0]["fields"], old_forms)
                (self.vault / "morphology.json").write_text('{broken json', encoding="utf-8")
                self.assertIn('morphology.json', request('/api/morphology/files', status=400)['error'])
                self.assertIn('morphology.json', request('/api/morphology/quiz', opts, status=400)['error'])
                self.assertEqual(request('/api/files')["files"][0]["name"], 'ch10.md')
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
