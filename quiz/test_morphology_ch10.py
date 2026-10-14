"""Chapter 10 reference tables and launch-readiness regressions.

Expected forms are explicit fixtures, independent of the generator's endings.
References: Dickinson College's Allen & Greenough adjective/i-stem paradigms,
deus_decl_0.pdf and 3rd_conj_io_verbs_pres.pdf (see README.md).
"""

from copy import deepcopy
from http.client import HTTPConnection
import json
from pathlib import Path
import random
import threading
import unittest

import morphology as m
import server
import vocab


VAULT = Path(__file__).resolve().parent.parent

NOUN_TABLES = {
    "deus": ("deus deī deō deum deō deus", "deī deōrum deīs deōs deīs deī"),
    "donum": ("dōnum dōnī dōnō dōnum dōnō dōnum", "dōna dōnōrum dōnīs dōna dōnīs dōna"),
    "equus": ("equus equī equō equum equō eque", "equī equōrum equīs equōs equīs equī"),
    "flamma": ("flamma flammae flammae flammam flammā flamma", "flammae flammārum flammīs flammās flammīs flammae"),
    "hostis": ("hostis hostis hostī hostem hoste hostis", "hostēs hostium hostibus hostēs hostibus hostēs"),
    "nox": ("nox noctis noctī noctem nocte nox", "noctēs noctium noctibus noctēs noctibus noctēs"),
    "periculum": ("perīculum perīculī perīculō perīculum perīculō perīculum", "perīcula perīculōrum perīculīs perīcula perīculīs perīcula"),
}

# A gender group of 'mf' applies the independently listed table to each gender.
ADJECTIVE_TABLES = [
    ("acer", "m", "ācer ācris ācrī ācrem ācrī ācer", "ācrēs ācrium ācribus ācrēs ācribus ācrēs"),
    ("acer", "f", "ācris ācris ācrī ācrem ācrī ācris", "ācrēs ācrium ācribus ācrēs ācribus ācrēs"),
    ("acer", "n", "ācre ācris ācrī ācre ācrī ācre", "ācria ācrium ācribus ācria ācribus ācria"),
    ("celeber", "m", "celeber celebris celebrī celebrem celebrī celeber", "celebrēs celebrium celebribus celebrēs celebribus celebrēs"),
    ("celeber", "f", "celebris celebris celebrī celebrem celebrī celebris", "celebrēs celebrium celebribus celebrēs celebribus celebrēs"),
    ("celeber", "n", "celebre celebris celebrī celebre celebrī celebre", "celebria celebrium celebribus celebria celebribus celebria"),
    ("felix", "mf", "fēlīx fēlīcis fēlīcī fēlīcem fēlīcī fēlīx", "fēlīcēs fēlīcium fēlīcibus fēlīcēs fēlīcibus fēlīcēs"),
    ("felix", "n", "fēlīx fēlīcis fēlīcī fēlīx fēlīcī fēlīx", "fēlīcia fēlīcium fēlīcibus fēlīcia fēlīcibus fēlīcia"),
    ("fortis", "mf", "fortis fortis fortī fortem fortī fortis", "fortēs fortium fortibus fortēs fortibus fortēs"),
    ("fortis", "n", "forte fortis fortī forte fortī forte", "fortia fortium fortibus fortia fortibus fortia"),
    ("pauci", "m", None, "paucī paucōrum paucīs paucōs paucīs paucī"),
    ("pauci", "f", None, "paucae paucārum paucīs paucās paucīs paucae"),
    ("pauci", "n", None, "pauca paucōrum paucīs pauca paucīs pauca"),
]

VERB_TABLES = [
    ("aedifico", "active", "aedificō aedificās aedificat aedificāmus aedificātis aedificant", "aedificāre"),
    ("aedifico", "passive", "aedificor aedificāris aedificātur aedificāmur aedificāminī aedificantur", "aedificārī"),
    ("capio", "active", "capiō capis capit capimus capitis capiunt", "capere"),
    ("capio", "passive", "capior caperis capitur capimur capiminī capiuntur", "capī"),
    ("cupio", "active", "cupiō cupis cupit cupimus cupitis cupiunt", "cupere"),
    ("cupio", "passive", "cupior cuperis cupitur cupimur cupiminī cupiuntur", "cupī"),
    ("deleo", "active", "dēleō dēlēs dēlet dēlēmus dēlētis dēlent", "dēlēre"),
    ("deleo", "passive", "dēleor dēlēris dēlētur dēlēmur dēlēminī dēlentur", "dēlērī"),
    ("fugio", "active", "fugiō fugis fugit fugimus fugitis fugiunt", "fugere"),
    ("moveo", "active", "moveō movēs movet movēmus movētis movent", "movēre"),
    ("moveo", "passive", "moveor movēris movētur movēmur movēminī moventur", "movērī"),
    ("pugno", "active", "pugnō pugnās pugnat pugnāmus pugnātis pugnant", "pugnāre"),
]


def answers_for(questions):
    return [{"fields": {f["key"]: f["answer"].split(" / ")[0]
                        for f in q["fields"] if not f["disabled"]}}
            for q in questions]


class Chapter10(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = vocab.parse_file(VAULT / "ch10.md", VAULT)
        cls.words = {(e.pos, e.headword): e for e in cls.pool}
        cls.lexicon = m.load_lexicon(include_custom=False)

    def build(self, pool=None, **opts):
        return m.build_quiz(self.pool if pool is None else pool, m.options(opts),
                            random.Random(10), self.lexicon)

    def test_complete_individual_and_pair_coverage(self):
        data = self.build(exhaustive=True, shuffle=False)
        self.assertEqual(data["counts"], {"noun": 7, "adjective": 5, "verb": 7, "pair": 7})
        self.assertEqual(data["pool"], 26)
        self.assertEqual(len(data["questions"]), 26)
        self.assertEqual([e["word"] for e in data["excluded"]], ["consilia capere"])
        standalone = {q["entry_key"] for q in data["questions"] if q["kind"] != "pair"}
        eligible = {e.key for e in self.pool if e.pos in ("noun", "adjective", "verb")
                    and e.headword != "consilia capere"}
        self.assertEqual(standalone, eligible)
        self.assertEqual(len(standalone), 19)
        self.assertTrue(all(q["source"] == "ch10.md" for q in data["questions"]))
        self.assertEqual(m.grade(data["questions"], answers_for(data["questions"]))["score"]["missed"], 0)

    def test_every_noun_cell_and_irregular_variants(self):
        for head, tables in NOUN_TABLES.items():
            model = m.noun_model(self.words["noun", head], self.lexicon)
            self.assertTrue(model.quantities_known)
            table = m.decline(model, model.genders[0])
            for number, expected in zip(m.NUMBERS, tables):
                with self.subTest(head=head, number=number):
                    self.assertEqual([table[case, number][0] for case in m.CASES], expected.split())
        deus = m.decline(self.lexicon.nouns["deus"], "m")
        for case in ("nominative", "vocative"):
            self.assertEqual(set(deus[case, "plural"]), {"deī", "diī", "dī"})
        for case in ("dative", "ablative"):
            self.assertEqual(set(deus[case, "plural"]), {"deīs", "diīs", "dīs"})
        self.assertEqual(set(deus["genitive", "plural"]), {"deōrum", "deum"})
        self.assertEqual(set(deus["vocative", "singular"]), {"deus", "dee"})
        for head, expected in (("hostis", {"hostēs", "hostīs"}), ("nox", {"noctēs", "noctīs"})):
            self.assertEqual(set(m.decline(self.lexicon.nouns[head], "m" if head == "hostis" else "f")
                                 ["accusative", "plural"]), expected)

    def test_every_adjective_cell_in_all_genders(self):
        for head, genders, singular, plural in ADJECTIVE_TABLES:
            model = m.adjective_model(self.words["adjective", head], self.lexicon)
            self.assertTrue(model.quantities_known)
            for gender in genders:
                table = m.decline(model, gender)
                for number, expected in zip(m.NUMBERS, (singular, plural)):
                    with self.subTest(head=head, gender=gender, number=number):
                        if expected is None:
                            self.assertTrue(all((case, number) not in table for case in m.CASES))
                        else:
                            self.assertEqual([table[case, number][0] for case in m.CASES], expected.split())

    def test_every_verb_person_and_matching_infinitive(self):
        for head, voice, expected, infinitive in VERB_TABLES:
            with self.subTest(head=head, voice=voice):
                model = m.verb_model(self.words["verb", head], self.lexicon)
                self.assertTrue(model.quantities_known)
                forms, inf = m.conjugate(model, voice)
                self.assertEqual([form[0] for form in forms], expected.split())
                self.assertEqual(inf, [infinitive])
                q = self.build([self.words["verb", head]], kinds=["verb"], voice=voice)["questions"][0]
                self.assertEqual(len(q["fields"]), 7)
                self.assertEqual(q["fields"][-1]["answer"],
                                 self.words["verb", head].latin_forms[1] if voice == "active" else infinitive)
                if voice == "passive":
                    alternate = {"aedifico": "aedificāre", "capio": "capere", "cupio": "cupere",
                                 "deleo": "dēlēre", "moveo": "movēre"}[head]
                    self.assertIn(alternate, forms[1])
                    answers = answers_for([q])
                    answers[0]["fields"]["p2_singular"] = alternate
                    self.assertEqual(m.grade([q], answers)["score"]["missed"], 0)

    def test_voice_restrictions_and_random_sampling(self):
        for head in ("fugio", "pugno"):
            with self.assertRaises(m.Unavailable):
                m.conjugate(m.verb_model(self.words["verb", head], self.lexicon), "passive")
        passive = self.build(kinds=["verb"], voice="passive", exhaustive=True)
        self.assertEqual(passive["counts"]["verb"], 5)
        self.assertEqual({e["word"] for e in passive["excluded"]}, {"fugio", "pugno", "consilia capere"})
        for voice in ("active", "mixed"):
            data = self.build(kinds=["verb"], voice=voice, count=7)
            self.assertEqual(len({q["entry_key"] for q in data["questions"]}), 7)
            self.assertTrue(all(q["voice"] == "active" for q in data["questions"]
                                if q["prompt"] in ("fugiō", "pugnō")))

    def test_every_pair_agrees_and_pauci_disables_singular(self):
        for head in NOUN_TABLES:
            noun = self.words["noun", head]
            gender = self.lexicon.nouns[head].genders[0]
            for adjective in ("acer", "celeber", "felix", "fortis", "pauci"):
                with self.subTest(noun=head, adjective=adjective):
                    q = self.build([noun, self.words["adjective", adjective]],
                                   kinds=["pair"], exhaustive=True)["questions"][0]
                    self.assertEqual(q["gender"], gender)
                    _, _, sg, pl = next(t for t in ADJECTIVE_TABLES if t[0] == adjective and gender in t[1])
                    expected = {f"{case}_{number}": f"{n} {a}"
                                for number, ns, ads in zip(m.NUMBERS, NOUN_TABLES[head], (sg, pl)) if ads
                                for case, n, a in zip(m.CASES, ns.split(), ads.split())}
                    for field in q["fields"]:
                        self.assertEqual(field["disabled"], field["key"] not in expected)
                        if not field["disabled"]:
                            # The chapter's dictionary slots override quantities
                            # in the independent reference tables above.
                            actual = field["answer"].split(" / ")[0]
                            self.assertEqual(vocab.normalize(actual), vocab.normalize(expected[field["key"]]))
                            case, number = field["key"].rsplit("_", 1)
                            if number == "singular" and case in ("nominative", "genitive"):
                                self.assertEqual(actual.split()[0], noun.latin_forms[0 if case == "nominative" else 1])
                            if case == "nominative" and number == ("plural" if adjective == "pauci" else "singular"):
                                adjective_entry = self.words["adjective", adjective]
                                if len(adjective_entry.latin_forms) == 3:
                                    self.assertEqual(actual.split()[1], adjective_entry.latin_forms["mfn".index(gender)])
                    answers = answers_for([q])
                    # Both noun/adjective word orders count as correct.
                    answers[0]["fields"] = {k: " ".join(reversed(v.split())) for k, v in answers[0]["fields"].items()}
                    result = m.grade([q], answers)
                    self.assertEqual(result["score"]["missed"], 0)
                    self.assertEqual(result["score"]["field_total"], 6 if adjective == "pauci" else 12)
                    if adjective == "pauci":
                        self.assertIn("Plural only.", q["notes"])

    def test_incorrect_infinitive_and_plural_table_retest(self):
        questions = self.build(kinds=["adjective", "verb"], voice="passive", gender="n",
                               exhaustive=True, shuffle=False)["questions"]
        answers = answers_for(questions)
        pauci = next(q for q in questions if q["prompt"].startswith("paucī"))
        capio = next(q for q in questions if q["prompt"] == "capiō")
        answers[pauci["index"]]["fields"]["genitive_plural"] = "paucarum"
        answers[capio["index"]]["fields"]["infinitive"] = "capere"
        result = m.grade(questions, answers)
        self.assertEqual(result["score"]["missed"], 2)
        retest = m.retest(questions, result["missed"], random.Random(10))
        self.assertEqual({q["identity"] for q in retest}, {pauci["identity"], capio["identity"]})
        for q in retest:
            original = next(old for old in questions if old["identity"] == q["identity"])
            self.assertEqual(q["fields"], original["fields"])
        self.assertEqual(m.grade(retest, answers_for(retest))["score"]["missed"], 0)


class Chapter10HTTP(unittest.TestCase):
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

    def request(self, path, payload=None):
        conn = HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=10)
        try:
            conn.request("GET" if payload is None else "POST", path,
                         None if payload is None else json.dumps(payload),
                         {} if payload is None else {"Content-Type": "application/json"})
            response = conn.getresponse()
            data = json.loads(response.read())
            self.assertEqual(response.status, 200, data)
            return data
        finally:
            conn.close()

    def test_launch_chapter10_quiz_grade_and_exact_retest(self):
        chapter = next(f for f in self.request('/api/morphology/files')["files"] if f["name"] == "ch10.md")
        self.assertEqual(chapter["by_pos"], {"noun": 7, "adjective": 5, "verb": 7})
        opts = {"files": ["ch10.md"], "exhaustive": True, "shuffle": False}
        pool = self.request('/api/morphology/pool', opts)
        self.assertEqual(pool["counts"], {"noun": 7, "adjective": 5, "verb": 7, "pair": 7})
        quiz = self.request('/api/morphology/quiz', opts)
        self.assertEqual(len(quiz["questions"]), 26)
        questions = deepcopy(server.QUIZZES[quiz["id"]]["questions"])
        answers = answers_for(questions)
        capio = next(q for q in questions if q["kind"] == "verb" and q["prompt"] == "capiō")
        answers[capio["index"]]["fields"]["infinitive"] = "wrong"
        result = self.request('/api/grade', {"id": quiz["id"], "answers": answers})
        self.assertEqual(result["score"]["missed"], 1)
        retest = self.request('/api/retest', {"id": quiz["id"]})
        self.assertEqual(retest["questions"], [{**quiz["questions"][capio["index"]], "index": 0}])
        original = server.QUIZZES[retest["id"]]["questions"]
        self.assertEqual(original[0]["fields"], capio["fields"])
        self.assertEqual(self.request('/api/grade', {"id": retest["id"], "answers": answers_for(original)})
                         ["score"]["missed"], 0)
        vocabulary = self.request('/api/quiz', {"files": ["ch10.md"], "exhaustive": True})
        self.assertEqual(len(vocabulary["questions"]), 21)


if __name__ == '__main__':
    unittest.main()
