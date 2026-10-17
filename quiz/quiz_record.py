"""Quiz records: legacy snapshots and compact references for Streamlit.

Reference records retain entry keys and the choices made for each occurrence.
Questions and answer keys are rebuilt from the installed, immutable chapters
and current morphology data. No catalog or engine revisions are archived.
"""

from copy import deepcopy
from dataclasses import replace
import json
import random

import morphology
import vocab


FORMAT = "latin-quiz-record"
VERSION = 1
REFERENCE_VERSION = 2
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


def _reference(q, kind):
    _require(isinstance(q, dict), "Invalid question reference in record.")
    _require(isinstance(q.get("entry"), str) and q["entry"], "Missing entry reference in record.")
    clean = {"entry": q["entry"]}
    if kind == "vocabulary":
        _require(q.get("direction") in MODES[:2], "Invalid question direction in record.")
        return {**clean, "direction": q["direction"]}
    _require(isinstance(q.get("kind"), str) and q["kind"] in morphology.KINDS,
             "Invalid morphology entry type in record.")
    clean["kind"] = q["kind"]
    choices = ({"voice": morphology.VOICES, "tense": morphology.TENSES, "mood": morphology.MOODS}
               if q["kind"] == "verb" else {"gender": morphology.GENDERS})
    for key, valid in choices.items():
        _require(isinstance(q.get(key), str) and q[key] in valid, f"Invalid morphology {key} in record.")
        clean[key] = q[key]
    if q["kind"] == "pair":
        _require(isinstance(q.get("adjective"), str) and q["adjective"],
                 "Missing adjective reference in record.")
        clean["adjective"] = q["adjective"]
    return clean


def _reference_from_question(q, index, kind):
    _require(isinstance(q, dict) and type(q.get("index")) is int and q["index"] == index,
             "Record questions must have consecutive indices in their test order.")
    ref = {"entry": q.get("entry_key")}
    if kind == "vocabulary":
        ref["direction"] = q.get("direction")
    else:
        ref["kind"] = q.get("kind")
        keys = ("voice", "tense", "mood") if ref["kind"] == "verb" else ("gender",)
        ref.update({key: q.get(key) for key in keys})
        if ref["kind"] == "pair":
            # Pair identities already contain both chapter entry keys.
            prefix = f"pair|{q.get('entry_key')}|"
            identity = q.get("identity", "")
            _require(isinstance(identity, str) and identity.startswith(prefix),
                     "Missing pair identity in record.")
            adjective, separator, gender = identity[len(prefix):].rpartition("|")
            _require(separator and gender == ref["gender"], "Invalid pair identity in record.")
            ref["adjective"] = adjective
    return _reference(ref, kind)


def _result(result, kind, count):
    _require(isinstance(result, dict), "Invalid result in record.")
    score = result.get("score")
    main = "main" if kind == "vocabulary" else "entry"
    score_keys = (f"{main}_correct", f"{main}_total", "field_correct", "field_total", "missed")
    _require(isinstance(score, dict) and all(type(score.get(key)) is int and score[key] >= 0
                                           for key in score_keys), "Invalid score in record.")
    _require(score[f"{main}_total"] == count and score[f"{main}_correct"] <= count
             and score["field_correct"] <= score["field_total"] and score["missed"] <= count,
             "Invalid score totals in record.")
    wrong = result.get("wrong")
    _require(isinstance(wrong, dict), "Invalid incorrect submissions in record.")
    clean_wrong = {}
    for index, fields in wrong.items():
        _require(isinstance(index, str) and index.isascii() and index.isdigit()
                 and len(index) <= 5 and str(int(index)) == index and int(index) < count,
                 "Invalid incorrect question index in record.")
        _require(_strings(fields) and fields and all(fields) and len(set(fields)) == len(fields),
                 "Invalid incorrect fields in record.")
        clean_wrong[index] = list(fields)
    unfamiliar = result.get("unfamiliar", [])
    _require(isinstance(unfamiliar, list)
             and all(type(index) is int and 0 <= index < count for index in unfamiliar)
             and len(set(unfamiliar)) == len(unfamiliar), "Invalid unfamiliar entries in record.")
    clean = {"score": {key: score[key] for key in score_keys}, "wrong": clean_wrong}
    if unfamiliar:
        clean["unfamiliar"] = list(unfamiliar)
    return clean


def validate(record):
    _require(isinstance(record, dict) and record.get("format") == FORMAT,
             "Choose a Latin quiz test record (.json).")
    _require(type(record.get("version")) is int and record["version"] in (VERSION, REFERENCE_VERSION),
             "Unsupported test record version.")
    kind = record.get("kind")
    opts = configuration(kind, record.get("configuration"))
    questions = record.get("questions")
    _require(isinstance(questions, list) and 0 < len(questions) <= 10000,
             "Record must contain between 1 and 10000 questions.")
    _require(type(record.get("retest", False)) is bool, "Invalid retest setting in record.")
    references = record["version"] == REFERENCE_VERSION
    clean = {"format": FORMAT, "version": record["version"], "kind": kind,
             "configuration": opts, "retest": record.get("retest", False),
             "questions": [_reference(q, kind) if references else _question(q, i, kind)
                           for i, q in enumerate(questions)]}
    if references and "result" in record:
        clean["result"] = _result(record["result"], kind, len(questions))
    return clean


def make_record(kind, opts, questions, retest=False, *, compact=False):
    """Streamlit uses compact references; legacy snapshot callers stay compatible."""
    if compact:
        questions = [_reference_from_question(q, i, kind) for i, q in enumerate(questions)]
    return validate({"format": FORMAT, "version": REFERENCE_VERSION if compact else VERSION,
                     "kind": kind, "configuration": opts, "questions": questions, "retest": retest})


def reconstruct(record, vault):
    """Build ordered runtime questions without drawing a new random test."""
    record = validate(record)
    if record["version"] == VERSION:
        return record["questions"]
    kind, opts, refs = record["kind"], record["configuration"], record["questions"]
    chapters = vocab.load_vault(vault)
    pool = [entry for name, entries in chapters.items() if name in opts["files"] for entry in entries]
    entries = {entry.key: entry for entry in pool}
    needed = {ref[key] for ref in refs for key in ("entry", "adjective") if key in ref}
    for key in sorted(needed):
        _require(key in entries, f"Recorded entry {key!r} is unavailable. Install the original chapter files.")
    questions = [None] * len(refs)
    if kind == "vocabulary":
        # Group by direction so repeated occurrences of one word may retain
        # different directions. The full selected pool supplies accepted twins.
        for direction in MODES[:2]:
            indices = [i for i, ref in enumerate(refs) if ref["direction"] == direction]
            generated = vocab.make_questions([entries[refs[i]["entry"]] for i in indices],
                                             pool, direction, opts["parsing"])
            for index, question in zip(indices, generated):
                question["index"] = index
                questions[index] = question
    else:
        # Resolve individual words first. A recorded pair supplies its actual
        # adjective instead of rerunning the random pair-selection algorithm.
        all_opts = morphology.options({"kinds": ["noun", "adjective", "verb"],
                                       "voices": list(morphology.VOICES),
                                       "tenses": list(morphology.TENSES), "moods": list(morphology.MOODS)})
        candidates, _, _ = morphology.candidates(
            [entry for entry in pool if entry.key in needed], all_opts,
            lexicon=morphology.load_lexicon(vault, include_cache=False), sources=morphology.table_sources(vault))
        available = {candidate["entry"].key: candidate for candidate in candidates}
        for index, ref in enumerate(refs):
            _require(ref["entry"] in available, f"Morphology is unavailable for recorded entry {ref['entry']!r}.")
            candidate = dict(available[ref["entry"]])
            expected_kind = "noun" if ref["kind"] == "pair" else ref["kind"]
            _require(candidate["kind"] == expected_kind, "Recorded entry has the wrong morphology type.")
            candidate["kind"] = ref["kind"]
            question_opts = dict(opts)
            if ref["kind"] == "verb":
                choice = tuple(ref[key] for key in ("voice", "tense", "mood"))
                _require(choice in candidate["configurations"], "Recorded verb configuration is unavailable.")
                candidate["configurations"] = [choice]
            else:
                question_opts["gender"] = ref["gender"]
                if ref["kind"] != "adjective":
                    _require(ref["gender"] in candidate["model"].genders, "Recorded noun gender is unavailable.")
                    candidate["model"] = replace(candidate["model"], genders=(ref["gender"],))
                if ref["kind"] == "pair":
                    adjective = available.get(ref["adjective"])
                    _require(adjective is not None and adjective["kind"] == "adjective",
                             "Recorded adjective is unavailable.")
                    candidate.update(adjective=adjective["entry"], adjective_model=adjective["model"],
                                     adjective_record=adjective["record"])
            questions[index] = morphology.question(candidate, index, question_opts, random.Random(0))
    for index, fields in record.get("result", {}).get("wrong", {}).items():
        question = questions[int(index)]
        allowed = {field["key"] for field in question["fields"] if not field.get("disabled")}
        if kind == "vocabulary":
            allowed.add("main")
        _require(set(fields) <= allowed, "Recorded result contains an unavailable answer field.")
    return questions


def with_result(record, questions, graded):
    """Keep only incorrect submission positions, score totals and review flags."""
    record = validate(record)
    if record["version"] == VERSION:
        return record
    _require(len(questions) == len(record["questions"]) == len(graded["results"]),
             "Result does not match the recorded test.")
    wrong, unfamiliar = {}, []
    for question, result in zip(questions, graded["results"]):
        fields = [field["key"] for field, outcome in zip(question["fields"], result["fields"])
                  if outcome["verdict"] == "wrong"]
        if record["kind"] == "vocabulary" and result["verdict"] == "wrong":
            fields.insert(0, "main")
        if fields:
            wrong[str(question["index"])] = fields
        if result.get("unfamiliar"):
            unfamiliar.append(question["index"])
    return validate({**record, "result": {"score": graded["score"], "wrong": wrong,
                                          "unfamiliar": unfamiliar}})


def dumps(record):
    return json.dumps(validate(record), ensure_ascii=False, separators=(",", ":"))


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
