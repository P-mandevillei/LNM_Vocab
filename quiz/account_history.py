"""Account identities, compact saved attempts and history practice selection."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
from io import BytesIO
import json
import re

import quiz_record


class HistoryError(ValueError):
    """A history action could not be completed; safe to display to the user."""


@dataclass(frozen=True)
class Identity:
    uid: str
    name: str
    email: str


def google_identity(claims):
    """Accept only the verified Google identity provided by Streamlit OIDC."""
    if not claims.get("is_logged_in"):
        return None
    issuer, subject = claims.get("iss"), claims.get("sub")
    if issuer not in ("accounts.google.com", "https://accounts.google.com"):
        raise HistoryError("Please sign in using Google.")
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise HistoryError("Google did not provide a valid account identity. Please sign in again.")
    if claims.get("email_verified") is not True and claims.get("email_verified") != "true":
        raise HistoryError("Please use a Google account with a verified email address.")
    uid = hashlib.sha256(f"https://accounts.google.com|{subject}".encode()).hexdigest()
    return Identity(uid, str(claims.get("name") or "Your account"), str(claims.get("email") or ""))


def valid_id(value, length=32):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def encode_record(record):
    record = quiz_record.validate(record)
    if record["version"] != quiz_record.REFERENCE_VERSION or "result" not in record:
        raise HistoryError("Only completed compact test records can be saved to your account.")
    payload = gzip.compress(quiz_record.dumps(record).encode("utf-8"), mtime=0)
    if len(payload) > 850_000:
        raise HistoryError("This test is too large to save. Download its test record to keep it.")
    return record, payload, hashlib.sha256(payload).hexdigest()


def decode_record(payload, digest):
    if not isinstance(payload, bytes) or not isinstance(digest, str):
        raise HistoryError("This saved test is incomplete.")
    if len(payload) > 850_000 or hashlib.sha256(payload).hexdigest() != digest:
        raise HistoryError("This saved test could not be verified.")
    try:
        with gzip.GzipFile(fileobj=BytesIO(payload)) as archive:
            raw = archive.read(quiz_record.MAX_BYTES + 1)
        record = quiz_record.loads(raw)
        if record["version"] != quiz_record.REFERENCE_VERSION or "result" not in record:
            raise ValueError("Missing compact result")
        return record
    except (ValueError, OSError, EOFError) as exc:
        raise HistoryError("This saved test record could not be read.") from exc


def attempt_document(owner, attempt_id, record, completed_at, source_ids=()):
    if not valid_id(owner, 64) or not valid_id(attempt_id):
        raise HistoryError("Please sign in again before saving this test.")
    if not isinstance(completed_at, datetime) or completed_at.tzinfo is None:
        raise HistoryError("The test completion time is missing.")
    if any(not valid_id(source_id) for source_id in source_ids) or len(source_ids) > 50:
        raise HistoryError("The practice test has invalid source tests.")
    record, payload, digest = encode_record(record)
    return {"schema_version": 1, "owner_id": owner, "attempt_id": attempt_id,
            "completed_at": completed_at.astimezone(timezone.utc), "kind": record["kind"],
            "retest": record["retest"], "entry_count": len(record["questions"]),
            "wrong_count": len(record["result"]["wrong"]), "score": record["result"]["score"],
            "files": record["configuration"]["files"], "source_attempt_ids": list(source_ids),
            "payload": payload, "payload_sha256": digest}


def recent_summary(attempts):
    summary = {"tests": len(attempts), "entries": 0, "wrong": 0,
               "vocabulary_correct": 0, "vocabulary_total": 0,
               "morphology_correct": 0, "morphology_total": 0}
    for attempt in attempts:
        summary["entries"] += attempt["entry_count"]
        summary["wrong"] += attempt["wrong_count"]
        score = attempt["score"]
        if attempt["kind"] == "vocabulary":
            summary["vocabulary_correct"] += score["main_correct"]
            summary["vocabulary_total"] += score["main_total"]
        else:
            summary["morphology_correct"] += score["field_correct"]
            summary["morphology_total"] += score["field_total"]
    return summary


def practice_record(records, selection="wrong"):
    """Union wrong question variants, newest first; all preserves one test's order."""
    if selection not in ("all", "wrong") or not records or (selection == "all" and len(records) != 1):
        raise HistoryError("Choose a test and a valid practice selection.")
    records = [quiz_record.validate(record) for record in records]
    kind = records[0]["kind"]
    if any(record["kind"] != kind or record["version"] != quiz_record.REFERENCE_VERSION
           or "result" not in record for record in records):
        raise HistoryError("Choose completed tests of the same type.")
    opts = deepcopy(records[0]["configuration"])
    opts["files"] = list(dict.fromkeys(name for record in records for name in record["configuration"]["files"]))
    questions, seen = [], set()
    if kind == "vocabulary":
        # A cumulative test can mix attempts with and without parsing.
        if len(records) > 1:
            opts["mode"] = "mixed"
        opts["parsing"] = any(record["configuration"]["parsing"] for record in records)
    else:
        for key in ("kinds", "voices", "tenses", "moods"):
            opts[key] = list(dict.fromkeys(value for record in records for value in record["configuration"][key]))
        if len(records) > 1:
            opts["gender"] = "mixed"
    for record in records:
        indices = (range(len(record["questions"])) if selection == "all"
                   else sorted(int(index) for index in record["result"]["wrong"]))
        for index in indices:
            ref = deepcopy(record["questions"][index])
            if kind == "vocabulary":
                parsing = ref.get("parsing", record["configuration"]["parsing"])
                ref.pop("parsing", None)
                if parsing != opts["parsing"]:
                    ref["parsing"] = parsing
            signature = json.dumps(ref, sort_keys=True, separators=(",", ":"))
            if selection == "wrong" and signature in seen:
                continue
            seen.add(signature)
            questions.append(ref)
    if not questions:
        raise HistoryError("There are no incorrect entries to retest in these tests.")
    if len(questions) > 10_000:
        raise HistoryError("Choose fewer recent tests to keep this practice test below 10,000 entries.")
    opts.update(count=min(len(questions), 500), exhaustive=False)
    opts.pop("retest_selection", None)
    return quiz_record.validate({"format": quiz_record.FORMAT, "version": quiz_record.REFERENCE_VERSION,
                                 "kind": kind, "configuration": opts, "retest": True, "questions": questions})
