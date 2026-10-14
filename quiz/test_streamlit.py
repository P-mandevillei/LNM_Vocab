"""Run real Streamlit reruns, forms and session state using AppTest.

Install requirements.txt to include these tests; plain-server-only installs
can still run the engine/HTTP suite without Streamlit.
"""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


HERE = Path(__file__).resolve().parent


class ChapterDiscovery(unittest.TestCase):
    def test_dependency_and_internal_markdown_is_not_a_chapter(self):
        import vocab
        with TemporaryDirectory() as directory:
            vault = Path(directory)
            for name in ("ch1.md", "notes/ch2.md", ".venv/package/README.md",
                         ".obsidian/internal.md", "quiz/MORPHOLOGY.md"):
                path = vault / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("**NOUNS**\naqua, aquae, f. - water", encoding="utf-8")
            self.assertEqual([path.relative_to(vault).as_posix() for path in vocab.find_markdown_files(vault)],
                             ["ch1.md", "notes/ch2.md"])


@unittest.skipUnless(AppTest, "Install requirements.txt to test the Streamlit app")
class StreamlitMorphology(unittest.TestCase):
    def app(self, **opts):
        app = AppTest.from_file(str(HERE / "streamlit_app.py"), default_timeout=30).run()
        self.healthy(app)
        app.multiselect(key="files").set_value(["ch10.md"])
        app.checkbox(key="exhaustive").set_value(opts.get("exhaustive", True))
        app.checkbox(key="shuffle").set_value(False)
        app.multiselect(key="morph_kinds").set_value(opts.get("kinds", ["noun", "adjective", "verb", "pair"]))
        voice = opts.get("voice", "mixed")
        app.multiselect(key="morph_voices").set_value(opts.get("voices", ["active", "passive"] if voice == "mixed" else [voice]))
        app.multiselect(key="morph_tenses").set_value(opts.get("tenses", ["present"]))
        app.multiselect(key="morph_moods").set_value(opts.get("moods", ["indicative"]))
        app.selectbox(key="morph_gender").set_value(opts.get("gender", "mixed"))
        app.run()
        self.healthy(app)
        return app

    def healthy(self, app):
        self.assertEqual([e.message for e in app.exception], [])

    def click(self, app, label):
        next(b for b in app.button if b.label == label).click().run()
        self.healthy(app)

    def fill_morphology(self, app, wrong=None, strip_macrons=False):
        import vocab
        for q in app.session_state["morph_quiz"]:
            for field in q["fields"]:
                if field["disabled"]:
                    continue
                answer = field["answer"].split(" / ")[0]
                if strip_macrons:
                    answer = vocab.strip_macrons(answer)
                if wrong and (q["index"], field["key"]) in wrong:
                    answer = "wrong"
                app.text_input(key=f"morph_ans_{q['index']}_{field['key']}").set_value(answer)

    def test_fresh_boot_has_both_tabs_and_chapter10_tables(self):
        app = self.app()
        self.assertEqual([t.label for t in app.tabs], ["Vocabulary", "Declension & conjugation"])
        self.assertTrue(any("26" in item.value and "eligible entries" in item.value for item in app.markdown))
        app.button(key="morph_start").click().run()
        self.healthy(app)
        self.assertEqual(len(app.session_state["morph_quiz"]), 26)
        # A new session after a reboot must also show the tab.
        fresh = AppTest.from_file(str(HERE / "streamlit_app.py"), default_timeout=30).run()
        self.healthy(fresh)
        self.assertEqual(len(fresh.tabs), 2)

    def test_passive_infinitive_grading_and_exact_retest(self):
        app = self.app(kinds=["verb"], voice="passive")
        app.button(key="morph_start").click().run()
        self.healthy(app)
        original = deepcopy(app.session_state["morph_quiz"])
        self.assertEqual(len(original), 5)
        capio = next(q for q in original if q["prompt"] == "capiō")
        self.assertTrue(all(q["voice"] == "passive" and len(q["fields"]) == 7 for q in original))
        self.fill_morphology(app, wrong={(capio["index"], "infinitive")})
        self.click(app, "Submit morphology answers")
        self.assertEqual(app.session_state["morph_results"]["score"]["missed"], 1)
        self.assertTrue(any("capī" in item.value and "Answer:" in item.value for item in app.markdown))
        app.button(key="morph_retest").click().run()
        self.healthy(app)
        questions = app.session_state["morph_quiz"]
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0], {**capio, "index": 0})
        self.assertTrue(all(not widget.value for widget in app.text_input))
        self.fill_morphology(app, strip_macrons=True)
        self.click(app, "Submit morphology answers")
        self.assertEqual(app.session_state["morph_results"]["score"]["missed"], 0)
        self.assertEqual(app.multiselect(key="morph_voices").value, ["passive"])

    def test_given_gender_plural_only_cells_and_agreement(self):
        app = self.app(kinds=["adjective", "pair"], gender="n")
        app.button(key="morph_start").click().run()
        self.healthy(app)
        questions = app.session_state["morph_quiz"]
        self.assertTrue(all(q["gender"] == "n" for q in questions if q["kind"] == "adjective"))
        pauci = next(q for q in questions if q["kind"] == "adjective" and q["prompt"].startswith("paucī"))
        for field in pauci["fields"]:
            widget = app.text_input(key=f"morph_ans_{pauci['index']}_{field['key']}")
            self.assertEqual(widget.disabled, field["key"].endswith("singular"))
        self.fill_morphology(app)
        self.click(app, "Submit morphology answers")
        result = app.session_state["morph_results"]
        self.assertEqual(result["score"]["missed"], 0)
        self.assertEqual(result["score"]["field_correct"], result["score"]["field_total"])

    def test_random_count_and_empty_selection(self):
        app = self.app(kinds=["verb"], exhaustive=False, voice="active")
        app.number_input(key="count").set_value(3).run()
        app.button(key="morph_start").click().run()
        self.healthy(app)
        questions = app.session_state["morph_quiz"]
        self.assertEqual(len(questions), 3)
        self.assertEqual(len({q["entry_key"] for q in questions}), 3)
        app.button(key="morph_start_over").click().run()
        app.multiselect(key="morph_kinds").set_value([]).run()
        self.healthy(app)
        self.assertTrue(any("Select at least one entry type" in item.value for item in app.info))

    def test_cached_tense_mood_and_multiselect_preferences(self):
        app = self.app(kinds=["verb"], voices=["active"], tenses=["imperfect"], moods=["subjunctive"])
        app.button(key="morph_start").click().run()
        self.healthy(app)
        qs = app.session_state["morph_quiz"]
        self.assertEqual(len(qs), 7)
        self.assertTrue(all(q["prompt_label"] == "Imperfect active subjunctive" for q in qs))
        self.assertTrue(all("rule" not in q["fields"][0]["answer_sources"] for q in qs))
        self.fill_morphology(app)
        self.click(app, "Submit morphology answers")
        self.assertEqual(app.session_state["morph_results"]["score"]["missed"], 0)
        app.button(key="morph_new").click().run()
        app.multiselect(key="morph_tenses").set_value(["present", "perfect"]).run()
        app.multiselect(key="morph_moods").set_value(["indicative", "subjunctive"]).run()
        self.healthy(app)
        self.assertEqual(app.multiselect(key="morph_tenses").value, ["present", "perfect"])
        self.assertEqual(app.multiselect(key="morph_moods").value, ["indicative", "subjunctive"])
        app.multiselect(key="morph_moods").set_value([]).run()
        self.assertTrue(any("valid verb moods" in item.value for item in app.error))

    def test_dictionary_and_disagreements_are_shown_only_in_results(self):
        app = self.app(kinds=["adjective"], gender="n")
        app.button(key="morph_start").click().run()
        self.healthy(app)
        qs = app.session_state["morph_quiz"]
        self.assertTrue(all("," not in q["prompt"] for q in qs))
        shown = " ".join(item.value for item in [*app.markdown, *app.caption])
        self.assertNotIn("fortunate", shown)
        self.assertNotIn("felicis", shown)
        self.assertNotIn("Rule and importer", shown)
        self.fill_morphology(app)
        self.click(app, "Submit morphology answers")
        shown = " ".join(item.value for item in [*app.markdown, *app.caption])
        self.assertIn("fortunate", shown)
        self.assertIn("felicis", shown)
        self.assertIn("⚠ Rule and importer spellings differ.", shown)
        self.assertIn("Chapter form takes precedence.", shown)

    def test_vocabulary_workflow_and_independent_sessions(self):
        app = self.app(exhaustive=False, kinds=["verb"], voice="active")
        app.number_input(key="count").set_value(2).run()
        self.click(app, "Start quiz")
        original_vocab = deepcopy(app.session_state["quiz"])
        app.button(key="morph_start").click().run()
        self.healthy(app)
        original_morph = deepcopy(app.session_state["morph_quiz"])
        self.assertEqual(app.session_state["quiz"], original_vocab)
        self.fill_morphology(app)
        self.click(app, "Submit morphology answers")
        self.assertEqual(app.session_state["quiz"], original_vocab)
        for q in original_vocab:
            app.text_input(key=f"ans_{q['index']}_main").set_value("wrong")
        self.click(app, "Submit answers")
        self.assertEqual(app.session_state["results"]["score"]["missed"], 2)
        self.assertEqual(app.session_state["morph_quiz"], original_morph)
        self.assertEqual(app.session_state["morph_results"]["score"]["missed"], 0)
        self.click(app, "Retest the 2 I missed")
        self.assertEqual(len(app.session_state["quiz"]), 2)
        self.assertEqual(app.session_state["morph_quiz"], original_morph)

    def test_vault_overrides_reload_without_changing_retest_snapshot(self):
        with TemporaryDirectory() as directory:
            vault = Path(directory)
            (vault / "ch10.md").write_text("**VERBS**\ncapio, capere, cepi, captum - take\n", encoding="utf-8")
            with patch.dict("os.environ", {"LATIN_VAULT": str(vault)}):
                app = self.app(kinds=["verb"], voice="passive")
                app.button(key="morph_start").click().run()
                self.healthy(app)
                original = deepcopy(app.session_state["morph_quiz"])
                self.fill_morphology(app, wrong={(0, "infinitive")})
                self.click(app, "Submit morphology answers")
                override = {"version": 1, "verbs": {"capio": {"overrides": {"passive": {"infinitive": ["capī", "fixture"]}}}}}
                (vault / "morphology.json").write_text(json.dumps(override), encoding="utf-8")
                app.button(key="morph_retest").click().run()
                self.assertEqual(app.session_state["morph_quiz"][0]["fields"], original[0]["fields"])
                app.button(key="morph_start_over").click().run()
                app.button(key="morph_start").click().run()
                self.healthy(app)
                self.assertEqual(app.session_state["morph_quiz"][0]["fields"][-1]["answer"], "capī / fixture")
                # Chapter edits also invalidate the data cache automatically.
                (vault / "ch10.md").write_text("**VERBS**\ncapio, capere, cepi, captum - take\n"
                                                "cupio, cupere, cupivi, cupitum - desire\n", encoding="utf-8")
                app.button(key="morph_start_over").click().run()
                app.button(key="morph_start").click().run()
                self.healthy(app)
                self.assertEqual(len(app.session_state["morph_quiz"]), 2)

    def test_unfamiliar_review_and_all_retest_selections_in_both_tabs(self):
        import quiz_record
        for kind in ("vocabulary", "morphology"):
            app = self.app(exhaustive=False, kinds=["verb"], voice="active")
            app.number_input(key="count").set_value(3).run()
            if kind == "morphology":
                app.button(key="morph_start").click().run()
                questions = deepcopy(app.session_state["morph_quiz"])
                self.fill_morphology(app, wrong={(1, "infinitive")})
                app.checkbox(key="morph_unfamiliar_0").set_value(True)
                submit = "Submit morphology answers"
                prefix = "morph_"
            else:
                self.click(app, "Start quiz")
                questions = deepcopy(app.session_state["quiz"])
                for q in questions:
                    app.text_input(key=f"ans_{q['index']}_main").set_value("wrong" if q["index"] == 1 else q["answer"].split(" / ")[0])
                    for f in q["fields"]:
                        app.text_input(key=f"ans_{q['index']}_{f['key']}").set_value(f["answer"].split(" / ")[0])
                app.checkbox(key="unfamiliar_0").set_value(True)
                submit = "Submit answers"
                prefix = ""
            self.click(app, submit)
            original_record = deepcopy(app.session_state[f"{prefix}record"])
            graded = app.session_state[f"{prefix}results"]
            self.assertEqual(quiz_record.retest_counts(kind, questions, graded["results"]),
                             {"wrong": 1, "unfamiliar": 1, "combined": 2})
            self.assertTrue(any(item.value == "Unfamiliar entries (1)" for item in app.subheader))
            remaining = next(e for e in app.expander if e.label.startswith("Remaining entries"))
            self.assertFalse(remaining.proto.expanded)
            if kind == "vocabulary":
                self.assertIn('qnum">2.', remaining.markdown[0].value)
                self.assertIn('qnum">3.', remaining.markdown[1].value)
            for selection, expected in (("wrong", [1]), ("unfamiliar", [0]), ("combined", [0, 1])):
                # Restore the same completed attempt for each independent choice.
                app.session_state[f"{prefix}quiz"] = deepcopy(questions)
                app.session_state[f"{prefix}record"] = deepcopy(original_record)
                app.session_state[f"{prefix}results"] = deepcopy(graded)
                app.session_state[f"{prefix}view"] = "results"
                app.run()
                app.selectbox(key=f"{prefix}retest_selection").set_value(selection).run()
                if prefix:
                    app.button(key="morph_retest").click().run()
                else:
                    button = next(b for b in app.button if b.label.startswith("Retest "))
                    button.click().run()
                self.healthy(app)
                retested = app.session_state[f"{prefix}quiz"]
                self.assertCountEqual([{**q, "index": 0} for q in retested],
                                      [{**questions[i], "index": 0} for i in expected])
                self.assertTrue(app.session_state[f"{prefix}record"]["retest"])
                flag_prefix = "morph_unfamiliar_" if prefix else "unfamiliar_"
                self.assertTrue(all(not c.value for c in app.checkbox if c.key and c.key.startswith(flag_prefix)))

    def test_record_restores_controls_exact_questions_and_independent_tabs(self):
        import quiz_record
        app = self.app(exhaustive=False, kinds=["verb"], voice="active")
        app.number_input(key="count").set_value(3).run()
        self.click(app, "Start quiz")
        original_vocab = deepcopy(app.session_state["quiz"])
        vocab_record = deepcopy(app.session_state["record"])
        app.button(key="morph_start").click().run()
        morph_record = deepcopy(app.session_state["morph_record"])
        for record in (vocab_record, morph_record):
            app.multiselect(key="files").set_value(["ch1.md"])
            app.number_input(key="count").set_value(1)
            app.checkbox(key="shuffle").set_value(True)
            app.run()
            app.session_state["pending_record"] = quiz_record.loads(quiz_record.dumps(record))
            app.run()
            self.healthy(app)
            prefix = "morph_" if record["kind"] == "morphology" else ""
            self.assertEqual(app.session_state[f"{prefix}quiz"], record["questions"])
            self.assertEqual(app.multiselect(key="files").value, ["ch10.md"])
            self.assertEqual(app.number_input(key="count").value, 3)
            self.assertFalse(app.checkbox(key="shuffle").value)
            self.assertTrue(all(not w.value for w in app.text_input))
        self.assertEqual(app.session_state["quiz"], original_vocab)
        self.assertEqual(app.multiselect(key="morph_voices").value, ["active"])
        app.session_state["pending_record"] = {"format": "wrong"}
        app.run()
        self.healthy(app)
        self.assertEqual(app.session_state["quiz"], original_vocab)
        self.assertTrue(any("Latin quiz test record" in e.value for e in app.error))

    def test_record_can_restore_when_source_chapter_is_missing(self):
        app = self.app(exhaustive=False, kinds=["verb"], voice="active")
        self.click(app, "Start quiz")
        record = deepcopy(app.session_state["record"])
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"LATIN_VAULT": directory}):
            fresh = AppTest.from_file(str(HERE / "streamlit_app.py"), default_timeout=30)
            fresh.session_state["pending_record"] = record
            fresh.run()
            self.healthy(fresh)
            self.assertEqual(fresh.session_state["quiz"], record["questions"])
            self.assertEqual(fresh.multiselect(key="files").value, ["ch10.md"])
            self.click(fresh, "Submit answers")
            self.assertEqual(fresh.session_state["results"]["score"]["missed"], 10)


if __name__ == '__main__':
    unittest.main()
