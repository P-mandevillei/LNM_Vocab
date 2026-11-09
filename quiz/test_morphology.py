"""Reference paradigms, sampling, grading and retesting.

Run: python -B -m unittest discover -s quiz -p 'test_*.py'
"""

from copy import deepcopy
from pathlib import Path
import random
import unittest

import morphology as m
import vocab

VAULT = Path(__file__).resolve().parent.parent


def entry(head, pos="noun"):
    found = next((e for group in vocab.load_vault(VAULT).values() for e in group
                  if e.pos == pos and vocab.normalize(e.headword) == vocab.normalize(head)), None)
    if found:
        return found
    # Reference tests also work when optional later chapter notes are absent.
    model = m.NOUNS.get(vocab.normalize(head)) if pos == "noun" else None
    if model:
        return vocab.Entry(list(model.forms), "reference fixture", pos, "fixture.md", 1,
                           gender="/".join(model.genders) + ".", number=model.number)
    verb = m.VERBS.get(vocab.normalize(head)) if pos == "verb" else None
    if verb:
        return vocab.Entry([verb.head, verb.infinitive], "reference fixture", pos, "fixture.md", 1)
    raise LookupError(head)


def nominal(head, gender=None, pos="noun"):
    e = entry(head, pos)
    model = m.adjective_model(e) if pos == "adjective" else m.noun_model(e)
    return m.decline(model, gender or model.genders[0])


def full_answers(questions, macrons=True):
    return [{"fields": {f["key"]: f["answer"].split(" / ")[0] if macrons
                        else vocab.strip_macrons(f["answer"].split(" / ")[0])
                        for f in q["fields"] if not f["disabled"]}}
            for q in questions]


class ReferenceForms(unittest.TestCase):
    def assertDeclension(self, head, singular, plural, gender=None, pos="noun"):
        forms = nominal(head, gender, pos)
        for number, expected in zip(m.NUMBERS, (singular, plural)):
            self.assertEqual([forms[c, number][0] for c in m.CASES], expected.split())

    def test_first_declension(self):
        self.assertDeclension("aqua", "aqua aquae aquae aquam aquā aqua",
                              "aquae aquārum aquīs aquās aquīs aquae")

    def test_second_er_and_neuter(self):
        self.assertDeclension("ager", "ager agrī agrō agrum agrō ager",
                              "agrī agrōrum agrīs agrōs agrīs agrī")
        self.assertDeclension("bellum", "bellum bellī bellō bellum bellō bellum",
                              "bella bellōrum bellīs bella bellīs bella")

    def test_lexical_vocatives_and_variants(self):
        forms = nominal("filius")
        self.assertEqual(forms["vocative", "singular"], ["fīlī"])
        self.assertEqual(forms["genitive", "singular"], ["fīliī", "fīlī"])
        self.assertEqual(nominal("filia")["dative", "plural"], ["fīliābus", "fīliīs"])
        self.assertEqual(nominal("meus", "m", "adjective")["vocative", "singular"], ["mī"])

    def test_third_consonant_and_i_stems(self):
        self.assertDeclension("rex", "rēx rēgis rēgī rēgem rēge rēx",
                              "rēgēs rēgum rēgibus rēgēs rēgibus rēgēs")
        self.assertDeclension("animal", "animal animālis animālī animal animālī animal",
                              "animālia animālium animālibus animālia animālibus animālia")
        self.assertDeclension("caput", "caput capitis capitī caput capite caput",
                              "capita capitum capitibus capita capitibus capita")
        self.assertEqual(nominal("urbs")["genitive", "plural"], ["urbium"])
        self.assertEqual(nominal("urbs")["accusative", "plural"], ["urbēs", "urbīs"])
        self.assertEqual(nominal("senex")["genitive", "plural"], ["senum"])

    def test_plural_only(self):
        for head, expected in [("castra", "castra castrōrum castrīs castra castrīs castra"),
                               ("tenebrae", "tenebrae tenebrārum tenebrīs tenebrās tenebrīs tenebrae")]:
            forms = nominal(head)
            self.assertEqual(len(forms), 6)
            self.assertEqual([forms[c, "plural"][0] for c in m.CASES], expected.split())
            self.assertNotIn(("nominative", "singular"), forms)

    def test_adjective_genders_and_er_stems(self):
        self.assertDeclension("pulcher", "pulcher pulchrī pulchrō pulchrum pulchrō pulcher",
                              "pulchrī pulchrōrum pulchrīs pulchrōs pulchrīs pulchrī", "m", "adjective")
        self.assertDeclension("miser", "miser miserī miserō miserum miserō miser",
                              "miserī miserōrum miserīs miserōs miserīs miserī", "m", "adjective")
        self.assertDeclension("magnus", "magna magnae magnae magnam magnā magna",
                              "magnae magnārum magnīs magnās magnīs magnae", "f", "adjective")
        self.assertDeclension("magnus", "magnum magnī magnō magnum magnō magnum",
                              "magna magnōrum magnīs magna magnīs magna", "n", "adjective")

    def test_reference_conjugations_and_infinitives(self):
        fixtures = [
            ("amo", "active", "amō amās amat amāmus amātis amant", "amāre"),
            ("amo", "passive", "amor amāris amātur amāmur amāminī amantur", "amārī"),
            ("habeo", "active", "habeō habēs habet habēmus habētis habent", "habēre"),
            ("habeo", "passive", "habeor habēris habētur habēmur habēminī habentur", "habērī"),
            ("dico", "active", "dīcō dīcis dīcit dīcimus dīcitis dīcunt", "dīcere"),
            ("dico", "passive", "dīcor dīceris dīcitur dīcimur dīciminī dīcuntur", "dīcī"),
            ("audio", "active", "audiō audīs audit audīmus audītis audiunt", "audīre"),
            ("audio", "passive", "audior audīris audītur audīmur audīminī audiuntur", "audīrī"),
            ("do", "active", "dō dās dat damus datis dant", "dare"),
            ("sum", "active", "sum es est sumus estis sunt", "esse"),
            ("possum", "active", "possum potes potest possumus potestis possunt", "posse"),
            ("iaceo", "active", "iaceō iacēs iacet iacēmus iacētis iacent", "iacēre"),
        ]
        for head, voice, expected, expected_inf in fixtures:
            with self.subTest(head=head, voice=voice):
                forms, inf = m.conjugate(m.verb_model(entry(head, "verb")), voice)
                self.assertEqual([f[0] for f in forms], expected.split())
                self.assertEqual(inf, [expected_inf])
        forms, _ = m.conjugate(m.verb_model(entry("amo", "verb")), "passive")
        self.assertEqual(forms[1], ["amāris", "amāre"])

    def test_no_invented_passives_and_early_aliases(self):
        for head in ("sum", "possum", "soleo", "venio", "do"):
            with self.subTest(head=head), self.assertRaises(m.Unavailable):
                m.conjugate(m.verb_model(entry(head, "verb")), "passive")
        self.assertEqual(m.verb_model(entry("amat", "verb")).head, "amō")
        self.assertEqual(m.verb_model(entry("est", "verb")).infinitive, "esse")


class QuestionsAndGrading(unittest.TestCase):
    def setUp(self):
        self.pool = [e for name, group in vocab.load_vault(VAULT).items()
                     if name in {f"ch{i}.md" for i in range(1, 9)} for e in group]

    def build(self, pool=None, **opts):
        return m.build_quiz(self.pool if pool is None else pool,
                            m.options(opts), random.Random(21))

    def test_corpus_coverage_and_exclusions(self):
        data = self.build(exhaustive=True, shuffle=False)
        self.assertEqual(data["counts"], {"noun": 58, "adjective": 13, "verb": 43, "pair": 58})
        self.assertEqual({e["word"] for e in data["excluded"]},
                         {"domī", "aestimo unius assis"})
        graded = m.grade(data["questions"], full_answers(data["questions"]))
        self.assertEqual(graded["score"]["entry_correct"], 172)
        self.assertEqual(graded["missed"], [])

    def test_selection_and_exhaustive_pair_coverage(self):
        pool = [entry("aqua"), entry("rex"), entry("magnus", "adjective"),
                entry("pulcher", "adjective"), entry("meus", "adjective")]
        data = self.build(pool, kinds=["pair"], exhaustive=True, shuffle=False)
        self.assertEqual(len(data["questions"]), 3)
        identities = " ".join(q["identity"] for q in data["questions"])
        for e in pool:
            self.assertIn(e.key, identities)
        self.assertEqual(len(self.build(pool, kinds=["noun"], count=1)["questions"]), 1)
        self.assertEqual(len(self.build(pool, kinds=["noun"], count=7)["questions"]), 7)

    def test_unshuffled_random_draw_keeps_chapter_order(self):
        pool = [entry("aqua"), entry("rex"), entry("ager")]
        data = self.build(pool, kinds=["noun"], count=3, shuffle=False)
        self.assertEqual([q["entry_key"] for q in data["questions"]], [e.key for e in pool])

    def test_agreement_is_grammatical_gender_and_case_not_ending(self):
        pool = [entry("agricola"), entry("bonus", "adjective")]
        q = self.build(pool, kinds=["pair"], exhaustive=True)["questions"][0]
        fields = {f["key"]: f for f in q["fields"]}
        self.assertEqual(fields["nominative_singular"]["answer"], "agricola bonus")
        self.assertEqual(fields["genitive_singular"]["answer"], "agricolae bonī")
        self.assertIn("boni agricolae", fields["genitive_singular"]["accepted"])
        answers = full_answers([q])
        answers[0]["fields"]["nominative_singular"] = "agricola bona"
        result = m.grade([q], answers)
        self.assertEqual(result["score"]["field_correct"], 11)
        self.assertEqual(result["score"]["missed"], 1)

    def test_neuter_plural_pair_and_common_gender(self):
        q = self.build([entry("castra"), entry("longus", "adjective")],
                       kinds=["pair"], exhaustive=True)["questions"][0]
        fields = {f["key"]: f for f in q["fields"]}
        self.assertEqual(fields["genitive_plural"]["answer"], "castrōrum longōrum")
        self.assertTrue(fields["nominative_singular"]["disabled"])
        self.assertEqual(m.grade([q], full_answers([q]))["score"]["field_total"], 6)
        for seed in range(10):
            data = m.build_quiz([entry("civis"), entry("bonus", "adjective")],
                                m.options({"kinds": ["pair"], "exhaustive": True}), random.Random(seed))
            q = data["questions"][0]
            expected = "bonus" if q["gender"] == "m" else "bona"
            self.assertEqual(q["fields"][0]["answer"], f"civis {expected}")
            self.assertTrue(q["fields"][0]["chapter_precedence"])

    def test_only_selected_chapter_words_are_used(self):
        pool = vocab.load_vault(VAULT)["ch1.md"]
        data = self.build(pool, exhaustive=True)
        self.assertEqual(data["counts"], {"noun": 10, "adjective": 0, "verb": 4, "pair": 0})
        self.assertTrue(all(q["source"] == "ch1.md" for q in data["questions"]))
        self.assertEqual(self.build(pool, kinds=["pair"])["questions"], [])

    def test_passive_voice_and_gender_filters(self):
        data = self.build(kinds=["verb"], voice="passive", exhaustive=True)
        self.assertTrue(all(q["voice"] == "passive" for q in data["questions"]))
        self.assertTrue(all(len(q["fields"]) == 7 for q in data["questions"]))
        data = self.build(kinds=["adjective"], gender="f", exhaustive=True)
        self.assertTrue(all(q["gender"] == "f" for q in data["questions"]))

    def test_partial_credit_infinitive_and_macrons(self):
        questions = self.build([entry("amo", "verb")], kinds=["verb"], voice="passive")["questions"]
        grade = m.grade(questions, full_answers(questions, macrons=False))
        self.assertEqual(grade["missed"], [])
        self.assertEqual(grade["score"]["field_correct"], grade["score"]["field_total"])
        answers = full_answers(questions)
        answers[0]["fields"]["infinitive"] = "amare"
        grade = m.grade(questions, answers)
        self.assertEqual(grade["score"]["field_correct"], grade["score"]["field_total"] - 1)
        self.assertEqual(len(grade["missed"]), 1)

    def test_retest_preserves_entries_and_deduplicates_exact_repeats(self):
        q = self.build([entry("rex"), entry("meus", "adjective")], kinds=["pair"], count=1)["questions"][0]
        questions = [q, {**deepcopy(q), "index": 1}]
        grade = m.grade(questions, [])
        self.assertEqual(grade["missed"], [0])
        retested = m.retest(questions, grade["missed"], random.Random(2))
        self.assertEqual(retested, [q])
        self.assertIsNot(retested[0], q)
        answered = m.grade(retested, full_answers(retested))
        self.assertEqual(answered["missed"], [])

    def test_different_voices_for_same_word_are_separate_mistakes(self):
        pool = [entry("amo", "verb")]
        active = self.build(pool, kinds=["verb"], voice="active", count=1)["questions"][0]
        passive = self.build(pool, kinds=["verb"], voice="passive", count=1)["questions"][0]
        passive["index"] = 1
        self.assertEqual(m.grade([active, passive], [])["missed"], [0, 1])

    def test_unreviewed_classes_are_not_guessed(self):
        unknown = vocab.Entry(["ignis", "ignis"], "fire", "noun", "test.md", 1, gender="m.")
        with self.assertRaises(m.Unavailable):
            m.noun_model(unknown)
        unknown = vocab.Entry(["lego", "legere"], "read", "verb", "test.md", 1)
        with self.assertRaises(m.Unavailable):
            m.verb_model(unknown)
        # Safe extensions can be used, without pretending that unreviewed
        # vowel quantities are a reliable source of corrections.
        unknown = vocab.Entry(["rosa", "rosae"], "rose", "noun", "test.md", 1, gender="f.")
        self.assertFalse(m.noun_model(unknown).quantities_known)


if __name__ == '__main__':
    unittest.main()
