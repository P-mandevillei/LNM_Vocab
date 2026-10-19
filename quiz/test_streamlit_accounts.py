"""Run account saves, dashboard navigation and practice through Streamlit."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from account_history import Identity
import quiz_record
import streamlit_accounts as accounts
from test_account_history import FakeFirestore, OWNER_A, OWNER_B, completed_record


HERE = Path(__file__).resolve().parent


class AccountWorkflows(unittest.TestCase):
    def setUp(self):
        self.client = FakeFirestore()
        self.identity = Identity(OWNER_A, "First User", "first@gmail.com")
        self.settings = {
            "auth": {"redirect_uri": "https://fixture.streamlit.app/oauth2callback", "cookie_secret": "fixture-cookie",
                     "google": {"client_id": "fixture-client", "client_secret": "fixture-secret",
                                "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration"}},
            "firestore": {"project_id": "fixture-project", "service_account": {
                "project_id": "fixture-project", "client_email": "fixture@example.com",
                "private_key": "fixture-private-key", "token_uri": "https://oauth2.googleapis.com/token"}}}
        for patcher in (patch.object(accounts, "current_identity", side_effect=lambda: self.identity),
                        patch.object(accounts, "_settings", side_effect=lambda: self.settings),
                        patch.object(accounts, "_client", return_value=self.client)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = AppTest.from_file(str(HERE / "streamlit_app.py"), default_timeout=30).run()
        self.healthy()

    def healthy(self):
        self.assertEqual([error.message for error in self.app.exception], [])

    def click(self, label=None, key=None):
        button = self.app.button(key=key) if key else next(button for button in self.app.button if button.label == label)
        button.click().run()
        self.healthy()

    def submit(self, kind="vocabulary", wrong=(0,), count=3):
        template = completed_record(kind, count=count)
        self.app.session_state["pending_record"] = template
        self.app.session_state["_account_next_page"] = "Practice"
        self.app.run()
        self.healthy()
        prefix = "morph_" if kind == "morphology" else ""
        questions = deepcopy(self.app.session_state[f"{prefix}quiz"])
        for question in questions:
            if not prefix:
                self.app.text_input(key=f"ans_{question['index']}_main").set_value(
                    "private response" if question["index"] in wrong else question["answer"].split(" / ")[0])
            first = True
            for field in question["fields"]:
                if field.get("disabled"):
                    continue
                value = field["answer"].split(" / ")[0]
                if prefix and first and question["index"] in wrong:
                    value = "private response"
                self.app.text_input(key=f"{prefix}ans_{question['index']}_{field['key']}").set_value(value)
                first = False
        self.click("Submit morphology answers" if prefix else "Submit answers")
        return deepcopy(self.app.session_state[f"{prefix}record"])

    def history(self):
        self.app.radio(key="account_page").set_value("Account").run()
        self.healthy()

    def open_only_test(self):
        self.history()
        self.click("View test")

    def test_submission_saves_once_and_detail_retests_every_entry_as_new_attempt(self):
        original = self.submit(count=4, wrong=(0, 1))
        self.assertEqual(len(self.client.documents), 1)
        self.assertTrue(any("Saved to your account" in caption.value for caption in self.app.caption))
        self.app.run()
        self.assertEqual(len(self.client.writes), 1)
        self.open_only_test()
        source_id = self.app.session_state["_account_detail_id"]
        self.assertEqual(self.app.session_state["_account_detail"]["record"], original)
        self.click(key="account_retest_all")
        self.assertEqual(self.app.session_state["account_page"], "Practice")
        self.assertEqual(len(self.app.session_state["quiz"]), 4)
        self.assertNotIn("result", self.app.session_state["record"])
        self.assertEqual(self.app.session_state["_account_attempt_vocabulary"]["source_ids"], [source_id])
        self.assertTrue(all(not widget.value for widget in self.app.text_input))
        self.click("Submit answers")
        self.assertEqual(len(self.client.documents), 2)
        saved_original = next(doc for doc in self.client.documents.values() if doc["attempt_id"] == source_id)
        self.assertEqual(saved_original["score"], original["result"]["score"])

    def test_detail_retests_only_wrong_entries_and_preserves_morphology_target(self):
        record = self.submit("morphology", wrong=(1,), count=4)
        self.open_only_test()
        self.click(key="account_retest_wrong")
        questions = self.app.session_state["morph_quiz"]
        self.assertEqual(len(questions), 1)
        self.assertEqual(self.app.session_state["morph_record"]["questions"], [record["questions"][1]])
        self.assertEqual(self.app.session_state["_practice_tab"], "Declension & conjugation")
        self.assertEqual(len(self.client.documents), 1)

    def test_recent_mistakes_include_both_attempts_and_summary_is_weighted(self):
        first = self.submit(wrong=(0,))
        second = self.submit(wrong=(1,))
        self.history()
        metrics = {metric.label: metric.value for metric in self.app.metric}
        self.assertEqual(metrics["Tests completed"], "2")
        self.assertEqual(metrics["Vocabulary accuracy"], "67%")
        reads = self.client.queries
        self.app.run()
        self.assertEqual(self.client.queries, reads)
        self.click(key="account_recent_vocabulary")
        self.assertEqual(self.app.session_state["record"]["questions"],
                         [second["questions"][1], first["questions"][0]])
        self.assertEqual(len(self.app.session_state["_account_attempt_vocabulary"]["source_ids"]), 2)
        self.assertNotIn("result", self.app.session_state["record"])

    def test_save_failure_stays_queued_and_retry_is_explicit(self):
        self.client.fail_before_write = True
        self.submit()
        self.assertEqual(len(self.client.documents), 0)
        pending = self.app.session_state["_account_pending_saves"]
        self.assertEqual(len(pending), 1)
        self.assertTrue(all("credential details" not in warning.value for warning in self.app.warning))
        self.app.run()
        self.assertEqual(len(self.client.writes), 1)
        self.click(key="account_retry_vocabulary")
        self.assertEqual(len(self.client.documents), 1)
        self.assertEqual(len(self.app.session_state["_account_pending_saves"]), 0)
        self.assertTrue(any("Saved to your account" in caption.value for caption in self.app.caption))

    def test_account_switch_discards_another_users_history_and_pending_saves(self):
        self.submit()
        self.open_only_test()
        self.assertIn("_account_detail", self.app.session_state)
        self.identity = Identity(OWNER_B, "Second User", "second@gmail.com")
        self.app.run()
        self.healthy()
        self.assertNotIn("_account_detail", self.app.session_state)
        self.assertNotIn("_account_pending_saves", self.app.session_state)
        self.assertIsNone(self.app.session_state["quiz"])
        self.history()
        self.assertTrue(any("No saved tests yet" in info.value for info in self.app.info))
        self.assertEqual(len(self.client.documents), 1)

    def test_guest_submission_never_writes_to_firestore(self):
        self.identity = None
        self.app.run()
        self.healthy()
        self.submit()
        self.assertEqual(self.client.documents, {})
        self.assertNotIn("_account_pending_saves", self.app.session_state)

    def test_visiting_account_keeps_practice_settings(self):
        self.app.multiselect(key="files").set_value(["ch10.md"])
        self.app.number_input(key="count").set_value(7)
        self.app.checkbox(key="parsing").set_value(False)
        self.app.multiselect(key="morph_voices").set_value(["active"])
        self.app.run()
        self.history()
        self.app.run()
        self.app.radio(key="account_page").set_value("Practice").run()
        self.healthy()
        self.assertEqual(self.app.multiselect(key="files").value, ["ch10.md"])
        self.assertEqual(self.app.number_input(key="count").value, 7)
        self.assertFalse(self.app.checkbox(key="parsing").value)
        self.assertEqual(self.app.multiselect(key="morph_voices").value, ["active"])
        self.assertEqual(self.client.documents, {})

    def test_missing_configuration_allows_guest_practice_and_explains_setup(self):
        self.identity = None
        self.settings = {}
        self.app.run()
        self.healthy()
        self.assertTrue(self.app.button(key="account_login").disabled)
        self.assertEqual([tab.label for tab in self.app.tabs], ["Vocabulary", "Declension & conjugation"])
        self.history()
        self.assertTrue(any("Sign in with Google" in info.value for info in self.app.info))


if __name__ == "__main__":
    unittest.main()
