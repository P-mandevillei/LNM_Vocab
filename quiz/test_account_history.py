"""Identity isolation, immutable saves and cumulative-practice behavior."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
from tempfile import TemporaryDirectory
import tomllib
import unittest
from unittest.mock import patch

from google.api_core.exceptions import AlreadyExists
from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import Client, DocumentSnapshot
from google.cloud.firestore_v1._helpers import encode_dict
from google.cloud.firestore_v1.query import Query
from google.cloud.firestore_v1.types import Document

from account_history import (HistoryError, attempt_document, decode_record, encode_record,
                             google_identity, practice_record, recent_summary)
from configure_accounts import ConfigurationError, configuration, write_configuration
from firestore_history import FirestoreHistory
import morphology
import quiz_record
import vocab


VAULT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 17, 17, 0, tzinfo=timezone.utc)
OWNER_A, OWNER_B = "a" * 64, "b" * 64


def completed_record(kind="vocabulary", count=3, wrong=(0,), parsing=True, direction="mixed"):
    pool = vocab.load_vault(VAULT)["ch10.md"]
    opts = dict(files=["ch10.md"], count=count, exhaustive=False, shuffle=True)
    if kind == "vocabulary":
        opts.update(mode=direction, parsing=parsing)
        questions = vocab.build_quiz(pool, count, direction, parsing, random.Random(7))
        grader = vocab.grade
    else:
        opts = {**opts, **morphology.options(opts)}
        questions = morphology.build_quiz(pool, opts, random.Random(7))["questions"]
        grader = morphology.grade
    answers = [{**({"main": q["answer"].split(" / ")[0]} if kind == "vocabulary" else {}),
                "fields": {field["key"]: field["answer"].split(" / ")[0] for field in q["fields"]}}
               for q in questions]
    for index in wrong:
        if kind == "vocabulary":
            answers[index]["main"] = "private answer text"
        else:
            key = next(field["key"] for field in questions[index]["fields"] if not field["disabled"])
            answers[index]["fields"][key] = "private answer text"
    record = quiz_record.make_record(kind, opts, questions, compact=True)
    return quiz_record.with_result(record, questions, grader(questions, answers))


class Snapshot:
    def __init__(self, path, document):
        self.path, self.id = path, path.rsplit("/", 1)[-1]
        self.document = deepcopy(document)
        self.exists = document is not None

    def to_dict(self):
        return deepcopy(self.document)


class FakeDocument:
    def __init__(self, client, path):
        self.client, self.path = client, path

    def collection(self, name):
        return FakeQuery(self.client, self.path + "/" + name)

    def create(self, document, **kwargs):
        self.client.writes.append(self.path)
        if self.path in self.client.documents:
            raise AlreadyExists("exists")
        if self.client.fail_before_write:
            self.client.fail_before_write = False
            raise TimeoutError("credential details must never reach the UI")
        self.client.documents[self.path] = deepcopy(document)
        if self.client.fail_after_write:
            self.client.fail_after_write = False
            raise TimeoutError("response lost after successful commit")

    def get(self, **kwargs):
        self.client.reads.append(self.path)
        return Snapshot(self.path, self.client.documents.get(self.path))


class FakeQuery:
    def __init__(self, client, path, fields=None, cursor=None, maximum=None):
        self.client, self.path = client, path
        self.fields, self.cursor, self.maximum = fields, cursor, maximum

    def document(self, name):
        return FakeDocument(self.client, self.path + "/" + name)

    def select(self, fields):
        return FakeQuery(self.client, self.path, fields, self.cursor, self.maximum)

    def order_by(self, field, direction):
        if field != "completed_at" or direction != "DESCENDING":
            raise AssertionError("Unexpected query")
        return self

    def start_after(self, cursor):
        return FakeQuery(self.client, self.path, self.fields, cursor, self.maximum)

    def limit(self, maximum):
        return FakeQuery(self.client, self.path, self.fields, self.cursor, maximum)

    def stream(self, **kwargs):
        self.client.queries += 1
        rows = [(path, doc) for path, doc in self.client.documents.items()
                if path.startswith(self.path + "/") and path.count("/") == self.path.count("/") + 1]
        rows.sort(key=lambda pair: (pair[1]["completed_at"], pair[0]), reverse=True)
        if self.cursor:
            cursor_key = (self.cursor.document["completed_at"], self.cursor.path)
            rows = [pair for pair in rows if (pair[1]["completed_at"], pair[0]) < cursor_key]
        for path, document in rows[:self.maximum]:
            self.client.reads.append(path)
            selected = {key: document[key] for key in self.fields} if self.fields else document
            yield Snapshot(path, selected)


class FakeFirestore:
    def __init__(self):
        self.documents, self.reads, self.writes = {}, [], []
        self.queries = 0
        self.fail_before_write = self.fail_after_write = False

    def collection(self, name):
        return FakeQuery(self, name)

    def get_all(self, references, **kwargs):
        # Firestore does not promise the order of batch results.
        return [reference.get() for reference in reversed(references)]


class IdentityTests(unittest.TestCase):
    def test_google_subject_is_stable_across_email_changes(self):
        claims = dict(is_logged_in=True, iss="https://accounts.google.com", sub="123",
                      email_verified=True, email="first@gmail.com", name="First")
        first = google_identity(claims)
        claims.update(iss="accounts.google.com", email="second@gmail.com", name="Second")
        self.assertEqual(first.uid, google_identity(claims).uid)
        claims["sub"] = "456"
        self.assertNotEqual(first.uid, google_identity(claims).uid)

    def test_missing_unverified_or_non_google_claims_are_rejected(self):
        self.assertIsNone(google_identity({"is_logged_in": False}))
        baseline = dict(is_logged_in=True, iss="https://accounts.google.com", sub="123", email_verified=True)
        for change in ({"iss": "https://example.com"}, {"sub": ""}, {"email_verified": False},
                       {"email_verified": "false"}, {"email_verified": 1}):
            with self.subTest(change=change), self.assertRaises(HistoryError):
                google_identity({**baseline, **change})


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeFirestore()
        self.store = FirestoreHistory(self.client, OWNER_A)
        self.record = completed_record()

    def test_account_scope_and_ownership_cannot_read_another_account(self):
        attempt_id = "1" * 32
        self.store.save(attempt_id, self.record, NOW)
        other = FirestoreHistory(self.client, OWNER_B)
        self.assertEqual(other.list_page().attempts, [])
        with self.assertRaises(HistoryError):
            other.get(attempt_id)
        with self.assertRaises(HistoryError):
            other.get_many([attempt_id])
        for bad_id in ("../" + attempt_id, "", OWNER_A, "users/other/test"):
            with self.assertRaises(HistoryError):
                self.store.get(bad_id)
        # Even a corrupt document in an owner's collection is checked again.
        path = f"latin_accounts/{OWNER_A}/attempts/{attempt_id}"
        self.client.documents[path]["owner_id"] = OWNER_B
        with self.assertRaises(HistoryError):
            self.store.get(attempt_id)

    def test_uncertain_save_retries_are_idempotent_and_do_not_overwrite(self):
        attempt_id = "1" * 32
        self.client.fail_after_write = True
        with self.assertRaises(TimeoutError):
            self.store.save(attempt_id, self.record, NOW)
        self.store.save(attempt_id, self.record, NOW + timedelta(days=1))
        self.assertEqual(len(self.client.documents), 1)
        self.assertEqual(self.store.get(attempt_id)["completed_at"], NOW)
        changed = completed_record(wrong=())
        with self.assertRaisesRegex(HistoryError, "different result"):
            self.store.save(attempt_id, changed, NOW)

    def test_pagination_ties_and_batch_order_preserve_every_attempt(self):
        ids = [f"{index:032x}" for index in range(7)]
        for attempt_id in ids:
            self.store.save(attempt_id, self.record, NOW)
        seen, cursor = [], None
        while True:
            page = self.store.list_page(3, cursor)
            seen.extend(row["attempt_id"] for row in page.attempts)
            self.assertTrue(all("payload" not in row and "record" not in row for row in page.attempts))
            cursor = page.cursor
            if cursor is None:
                break
        self.assertEqual(seen, list(reversed(ids)))
        wanted = [ids[0], ids[4], ids[2]]
        self.assertEqual([row["attempt_id"] for row in self.store.get_many(wanted)], wanted)

    def test_payload_is_compact_and_real_firestore_encoding_accepts_it(self):
        document = attempt_document(OWNER_A, "1" * 32, self.record, NOW)
        serialized = Document(fields=encode_dict(document))._pb.SerializeToString()
        self.assertLess(len(serialized), 1_048_576)
        self.assertEqual(decode_record(document["payload"], document["payload_sha256"]), self.record)
        self.assertNotIn(b"private answer text", quiz_record.dumps(self.record).encode())
        bad = document["payload"] + b"corrupt"
        with self.assertRaises(HistoryError):
            decode_record(bad, document["payload_sha256"])
        with self.assertRaises(HistoryError):
            decode_record(bad, hashlib.sha256(bad).hexdigest())

    def test_actual_sdk_projection_and_cursor_build_without_extra_indexes(self):
        client = Client(project="fixture-project", credentials=AnonymousCredentials())
        store = FirestoreHistory(client, OWNER_A)
        snapshots = []
        for attempt_id in ("2" * 32, "1" * 32):
            document = attempt_document(OWNER_A, attempt_id, self.record, NOW)
            snapshots.append(DocumentSnapshot(store.collection.document(attempt_id), document,
                                              True, NOW, NOW, NOW))
        with patch.object(Query, "stream", autospec=True, return_value=iter(snapshots)) as stream:
            page = store.list_page(1)
            query = stream.call_args.args[0]._to_protobuf()
            self.assertEqual([item.field.field_path for item in query.order_by], ["completed_at"])
            self.assertNotIn("payload", [item.field_path for item in query.select.fields])
        with patch.object(Query, "stream", autospec=True, return_value=iter([])) as stream:
            store.list_page(1, page.cursor)
            query = stream.call_args.args[0]._to_protobuf()
            self.assertEqual(len(query.start_at.values), 2)
            self.assertEqual([item.field.field_path for item in query.order_by],
                             ["completed_at", "__name__"])
        client.close()

    def test_weighted_recent_summary_uses_totals_not_average_percentages(self):
        rows = [dict(kind="vocabulary", entry_count=1, wrong_count=0,
                     score=dict(main_correct=1, main_total=1)),
                dict(kind="vocabulary", entry_count=9, wrong_count=9,
                     score=dict(main_correct=0, main_total=9))]
        summary = recent_summary(rows)
        self.assertEqual(summary["vocabulary_correct"] / summary["vocabulary_total"], 0.1)
        self.assertEqual(summary["tests"], 2)


class PracticeTests(unittest.TestCase):
    def test_every_entry_preserves_order_and_wrong_entries_are_deduplicated(self):
        record = completed_record(count=50, wrong=(0, 1, 2))
        all_entries = practice_record([record], "all")
        self.assertEqual(all_entries["questions"], record["questions"])
        self.assertNotIn("result", all_entries)
        self.assertTrue(all_entries["retest"])
        mistakes = practice_record([record, record], "wrong")
        expected = list({json.dumps(record["questions"][i], sort_keys=True): record["questions"][i]
                         for i in (0, 1, 2)}.values())
        self.assertEqual(mistakes["questions"], expected)

    def test_cumulative_vocabulary_preserves_both_directions_and_parsing_choices(self):
        records = [completed_record(count=1, parsing=True, direction="en_to_la"),
                   completed_record(count=1, parsing=False, direction="en_to_la"),
                   completed_record(count=1, parsing=True, direction="la_to_en")]
        record = practice_record(records)
        questions = quiz_record.reconstruct(record, VAULT)
        self.assertEqual(len(questions), 3)
        self.assertEqual(questions[0]["direction"], questions[1]["direction"])
        self.assertNotEqual(questions[0]["direction"], questions[2]["direction"])
        self.assertTrue(questions[0]["fields"])
        self.assertEqual(questions[1]["fields"], [])
        regenerated = quiz_record.make_record("vocabulary", record["configuration"], questions, compact=True)
        self.assertEqual(quiz_record.reconstruct(regenerated, VAULT), questions)

    def test_morphology_practice_reconstructs_and_rejects_mixed_types(self):
        record = completed_record("morphology", count=20, wrong=(0, 1, 2))
        practice = practice_record([record, record])
        self.assertEqual(len(practice["questions"]), 3)
        self.assertEqual(len(quiz_record.reconstruct(practice, VAULT)), 3)
        with self.assertRaises(HistoryError):
            practice_record([record, completed_record()])
        with self.assertRaises(HistoryError):
            practice_record([completed_record(wrong=())])


class ConfigurationTests(unittest.TestCase):
    def credentials(self):
        return ({"web": {"client_id": "fixture-client", "client_secret": "private-oauth-secret",
                         "redirect_uris": ["https://latin.streamlit.app/oauth2callback"]}},
                {"type": "service_account", "project_id": "fixture-project", "client_email": "fixture@example.com",
                 "private_key": "-----BEGIN PRIVATE KEY-----\nfixture\n-----END PRIVATE KEY-----\n",
                 "token_uri": "https://oauth2.googleapis.com/token"})

    def test_configuration_roundtrips_pem_and_generates_distinct_cookie_secrets(self):
        oauth, service = self.credentials()
        first = tomllib.loads(configuration(oauth, service, "https://latin.streamlit.app"))
        second = tomllib.loads(configuration(oauth, service, "https://latin.streamlit.app/"))
        self.assertEqual(first["firestore"]["service_account"], service)
        self.assertEqual(first["auth"]["google"]["client_secret"], "private-oauth-secret")
        self.assertNotEqual(first["auth"]["cookie_secret"], second["auth"]["cookie_secret"])
        with self.assertRaisesRegex(ConfigurationError, "authorized redirect URI"):
            configuration(oauth, service, "https://other.streamlit.app")

    def test_configuration_never_overwrites_existing_secrets(self):
        oauth, service = self.credentials()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "oauth.json").write_text(json.dumps(oauth), encoding="utf-8")
            (root / "service.json").write_text(json.dumps(service), encoding="utf-8")
            destination = root / "secrets.toml"
            write_configuration(root / "oauth.json", root / "service.json", "https://latin.streamlit.app", destination)
            original = destination.read_bytes()
            with self.assertRaises(FileExistsError):
                write_configuration(root / "oauth.json", root / "service.json", "https://latin.streamlit.app", destination)
            self.assertEqual(destination.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
