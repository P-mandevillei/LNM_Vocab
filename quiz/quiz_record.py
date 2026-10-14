"""Portable, versioned quiz snapshots shared by both front ends.

Store the actual questions, including their answer keys, rather than a random
seed: mixed directions, agreement pairs and later chapter edits must replay
exactly. Responses and unfamiliar marks belong only to the current attempt.
"""

from copy import deepcopy
import json

import morphology
import vocab


FORMAT = "latin-quiz-record"
VERSION = 1
MAX_BYTES = 20 * 1024 * 1024
MODES = ("la_to_en", "en_to_la", "mixed")
RETEST_CHOICES = {"wrong": "Wrong entries only", "unfamiliar": "Unfamiliar entries only",
                  "combined": "Unfamiliar + wrong entries"}


def _require(condition, message="Invalid test record."):
    if not condition:
        raise ValueError(message)


def _strings(value):
    return isinstance(value, list) and all(isinstance(s, str) for s in value)


def configuration(kind, req):
    _require(kind in ("vocabulary", "morphology"), "Unknown tester in record.")
    _require(isinstance(req, dict), "Missing record configuration.")
    _require(_strings(req.get("files")), "Record chapters must be a list of names.")
    _require(type(req.get("count")) is int and 1 <= req["count"] <= 500,
             "Record question count must be between 1 and 500.")
    for key in ("exhaustive", "shuffle"):
        _require(type(req.get(key)) is bool, f"Invalid {key} setting in record.")
    if kind == "morphology":
        opts = morphology.options(req)
    else:
        _require(req.get("mode") in MODES, "Invalid vocabulary mode in record.")
        _require(type(req.get("parsing")) is bool, "Invalid parsing setting in record.")
        opts = {key: req[key] for key in ("mode", "parsing", "count", "exhaustive", "shuffle")}
    if "retest_selection" in req:
        _require(isinstance(req["retest_selection"], str) and req["retest_selection"] in RETEST_CHOICES,
                 "Invalid retest selection in record.")
        opts["retest_selection"] = req["retest_selection"]
    return {"files": list(req["files"]), **opts}


def _question(q, index, kind):
    _require(isinstance(q, dict) and type(q.get("index")) is int and q["index"] == index,
             "Record questions must have consecutive indices in their test order.")
    texts = ["prompt", "prompt_label", "source", "entry_key", "full_entry"]
    texts += ["direction", "pos", "answer"] if kind == "vocabulary" else ["kind", "identity"]
    _require(all(isinstance(q.get(key), str) for key in texts), "Incomplete question in record.")
    clean = {key: q[key] for key in ["index", *texts]}
    if kind == "vocabulary":
        _require(q["direction"] in MODES[:2], "Invalid question direction in record.")
        for key in ("accepted", "strict"):
            _require(_strings(q.get(key)), "Missing vocabulary answer key in record.")
            clean[key] = list(q[key])
    else:
        _require(q["kind"] in morphology.KINDS, "Invalid morphology entry type in record.")
        for key in ("rows", "columns", "notes"):
            _require(_strings(q.get(key)), "Incomplete morphology table in record.")
            clean[key] = list(q[key])
        expected_rows = ["1st person", "2nd person", "3rd person"] if q["kind"] == "verb" else [c.title() for c in morphology.CASES]
        _require(q["rows"] == expected_rows and q["columns"] == ["Singular", "Plural"],
                 "Invalid morphology table layout in record.")
        choices = {"voice": morphology.VOICES, "tense": morphology.TENSES, "mood": morphology.MOODS} if q["kind"] == "verb" else {"gender": morphology.GENDERS}
        for key, valid in choices.items():
            _require(isinstance(q.get(key), str) and q[key] in valid, f"Invalid morphology {key} in record.")
            clean[key] = q[key]

    _require(isinstance(q.get("fields"), list), "Missing question fields in record.")
    fields, keys = [], set()
    for f in q["fields"]:
        _require(isinstance(f, dict), "Invalid answer field in record.")
        _require(all(isinstance(f.get(key), str) for key in ("key", "label", "answer")),
                 "Incomplete answer field in record.")
        _require(f["key"] not in keys, "Duplicate answer field in record.")
        keys.add(f["key"])
        field = {key: f[key] for key in ("key", "label", "answer")}
        for key in ("accepted", "strict"):
            _require(_strings(f.get(key)), "Missing field answer key in record.")
            field[key] = list(f[key])
        if kind == "vocabulary":
            _require(isinstance(f.get("short"), str), "Incomplete parsing field in record.")
            field["short"] = f["short"]
        else:
            for key in ("disabled", "quantities_known", "disagreement", "chapter_precedence"):
                _require(type(f.get(key)) is bool, "Invalid morphology field in record.")
                field[key] = f[key]
            sources = f.get("answer_sources")
            _require(isinstance(sources, dict) and all(isinstance(k, str) and _strings(v) for k, v in sources.items()),
                     "Invalid answer sources in record.")
            field["answer_sources"] = deepcopy(sources)
        fields.append(field)
    if kind == "morphology":
        prefixes = [f"p{i}" for i in range(1, 4)] if q["kind"] == "verb" else morphology.CASES
        expected_keys = {f"{p}_{n}" for p in prefixes for n in morphology.NUMBERS}
        if q["kind"] == "verb":
            expected_keys.add("infinitive")
        _require(keys == expected_keys, "Incomplete morphology cells in record.")
    clean["fields"] = fields
    return clean


def validate(record):
    _require(isinstance(record, dict) and record.get("format") == FORMAT,
             "Choose a Latin quiz test record (.json).")
    _require(type(record.get("version")) is int and record["version"] == VERSION,
             "Unsupported test record version.")
    kind = record.get("kind")
    opts = configuration(kind, record.get("configuration"))
    questions = record.get("questions")
    _require(isinstance(questions, list) and 0 < len(questions) <= 10000,
             "Record must contain between 1 and 10000 questions.")
    _require(type(record.get("retest", False)) is bool, "Invalid retest setting in record.")
    return {"format": FORMAT, "version": VERSION, "kind": kind,
            "configuration": opts, "retest": record.get("retest", False),
            "questions": [_question(q, i, kind) for i, q in enumerate(questions)]}


def make_record(kind, opts, questions, retest=False):
    return validate({"format": FORMAT, "version": VERSION, "kind": kind,
                     "configuration": opts, "questions": questions, "retest": retest})


def dumps(record):
    return json.dumps(validate(record), ensure_ascii=False, indent=2)


def loads(data):
    _require(isinstance(data, (str, bytes)) and len(data) <= MAX_BYTES,
             "Test record is too large (maximum 20 MB).")
    try:
        if isinstance(data, bytes):
            data = data.decode("utf-8-sig")
        return validate(json.loads(data))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("The file is not a valid JSON test record.") from exc


def review_groups(results, unfamiliar):
    """Keep flagged entries visible and stable; sort the rest wrong-first."""
    marked = set(unfamiliar)
    first = [r for r in results if r["index"] in marked]
    remaining = [r for r in results if r["index"] not in marked]
    remaining.sort(key=lambda r: not vocab.is_mistake(r))
    return first, remaining


def retest_indices(kind, questions, results, selection="wrong"):
    _require(isinstance(selection, str) and selection in RETEST_CHOICES, "Choose a valid retest selection.")
    indices, seen = [], set()
    for q, r in zip(questions, results):
        selected = ((selection in ("wrong", "combined") and vocab.is_mistake(r))
                    or (selection in ("unfamiliar", "combined") and r.get("unfamiliar", False)))
        identity = q["identity"] if kind == "morphology" else q["entry_key"]
        if selected and identity not in seen:
            indices.append(q["index"])
            seen.add(identity)
    return indices


def retest_counts(kind, questions, results):
    return {choice: len(retest_indices(kind, questions, results, choice)) for choice in RETEST_CHOICES}
