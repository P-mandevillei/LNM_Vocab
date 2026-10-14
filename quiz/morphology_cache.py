"""Offline, versioned table-cache I/O and projection to the retained v1 schema.

No HTTP client is imported here. Acquired records are candidates for review;
only explicitly approved records can supplement the old lexical definitions.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from functools import lru_cache
import json
import hashlib
import os
from pathlib import Path
import tempfile
import time


SCHEMA_VERSION = 1
DEFAULT_CACHE = Path(__file__).resolve().parent / "data" / "morphology_cache.json"
STATUSES = {"ready", "ambiguous", "not_found", "error"}


class CacheError(ValueError):
    pass


def empty_cache():
    return {"schema_version": SCHEMA_VERSION, "entries": {}, "bindings": {}, "skipped": {}}


def load_cache(path=DEFAULT_CACHE):
    path = Path(path)
    if not path.exists():
        return empty_cache()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CacheError(f"{path}: {exc}") from exc
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data.get("schema_version") != SCHEMA_VERSION:
        raise CacheError(f"{path}: unsupported morphology cache schema")
    for key in ("entries", "bindings", "skipped"):
        if not isinstance(data.get(key), dict):
            raise CacheError(f"{path}: {key} must be an object")
    for key, record in data["entries"].items():
        if not isinstance(record, dict) or record.get("status") not in STATUSES:
            raise CacheError(f"{path}: invalid acquisition record {key}")
        if record.get("status") == "ready":
            candidate = record.get("candidate")
            if not isinstance(candidate, dict) or not isinstance(candidate.get("cells"), dict) or not candidate["cells"]:
                raise CacheError(f"{path}: {key} has no parsed cells")
            for name, cell in candidate["cells"].items():
                if (not isinstance(cell, dict) or not isinstance(cell.get("features"), dict) or
                        not isinstance(cell.get("forms"), list) or not isinstance(cell.get("source_forms"), list) or
                        any(not isinstance(f, str) or not f.strip() for f in cell["forms"]) or
                        name != "|".join(f"{k}={v}" for k, v in sorted(cell["features"].items())) or
                        cell.get("status") != ("available" if cell["forms"] else "unavailable")):
                    raise CacheError(f"{path}: invalid cell {key}: {name}")
    for binding in data["bindings"].values():
        if not isinstance(binding, dict) or binding.get("entry") not in data["entries"]:
            raise CacheError(f"{path}: invalid chapter binding")
    return data


def save_json(path, data):
    """Do not touch a byte-identical file; atomically replace a changed one."""
    path = Path(path)
    content = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if path.exists() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(9):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 8:
                    raise
                # Windows sync/indexing tools may briefly hold the old file.
                time.sleep(min(0.05 * 2 ** attempt, 0.5))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


@contextmanager
def cache_lock(path):
    lock = Path(str(path) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise CacheError(f"Import already locked: {lock}. Remove a stale lock only after checking no import is running.") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def lookup(candidate, **features):
    key = "|".join(f"{k}={v}" for k, v in sorted(features.items()))
    return candidate.get("cells", {}).get(key)


class TableSources:
    """Read ready imports independently of the approved legacy projection.

    Quiz policy permits imported alternatives, including unreviewed imports.
    Bindings retain grammatical identity; a word's gloss/chapter is immaterial.
    """

    def __init__(self, data):
        self.data = data
        self.by_dictionary = {}
        from vocab import normalize
        for record in data["entries"].values():
            if record["status"] == "ready":
                req = record["request"]
                key = (req["pos"], tuple(normalize(f) for f in req["forms"]))
                self.by_dictionary.setdefault(key, []).append(record)

    def record_for(self, entry, model=None):
        raw = {"pos": entry.pos, "forms": entry.latin_forms,
               "gender": entry.gender, "number": entry.number}
        key = hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")).encode()).hexdigest()
        binding = self.data["bindings"].get(key)
        if binding:
            record = self.data["entries"][binding["entry"]]
            return record if record["status"] == "ready" else None
        from vocab import normalize
        forms = ([model.head, model.infinitive] if entry.pos == "verb" else model.forms) if model else entry.latin_forms
        records = self.by_dictionary.get((entry.pos, tuple(normalize(f) for f in forms)), [])
        return records[0] if len(records) == 1 else None


def table_sources(vault=None, path=None):
    """Mtime-keyed read-only cache; chapter updates need no service restart."""
    local = Path(vault) / "morphology_cache.json" if vault else None
    path = Path(path) if path else local if local and local.exists() else DEFAULT_CACHE
    if not path.exists():
        return TableSources(empty_cache())
    stat = path.stat()
    return _table_sources(str(path.resolve()), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=8)
def _table_sources(path, modified, size):
    return TableSources(load_cache(path))


def legacy_record(request, candidate):
    """Project available drill cells, preserving chapter number/voice limits."""
    from morphology_data import CASES, NUMBERS, GENDERS
    pos, forms = request["pos"], request["forms"]
    number = request.get("number")
    quantities = False  # The provider's prosodic notation is retained separately.
    if pos in ("noun", "adjective"):
        tables = {}
        genders = request.get("genders") or ["m", "f", "n"]
        for gender in (genders if pos == "adjective" else [None]):
            table = {}
            for case in CASES:
                for num in NUMBERS:
                    if number and num != ("plural" if number == "pl" else "singular"):
                        continue
                    features = {"pos": pos, "case": case, "number": num}
                    if pos == "adjective":
                        features.update(gender=gender, degree="positive")
                    cell = lookup(candidate, **features)
                    if cell is None:
                        raise CacheError(f"Incomplete {pos} cache: {candidate['id']}: {features}")
                    table[f"{case}_{num}"] = cell["forms"] or None
            tables[gender] = table
        record = {"forms": forms, "declension": "custom", "quantities_known": quantities,
                  "overrides": tables if pos == "adjective" else tables[None]}
        if number:
            record["number"] = number
        if pos == "noun":
            record["gender"] = "/".join(genders)
        return record
    if pos == "verb":
        paradigms = {}
        # Retain complete passive data, but never enable it without an explicit
        # reviewed chapter restriction/definition.
        for voice in ("active", "passive"):
            table = {}
            for num in NUMBERS:
                for person in range(1, 4):
                    cell = lookup(candidate, pos="verb", mood="indicative", tense="present",
                                  voice=voice, person=person, number=num)
                    if cell and cell["forms"]:
                        table[f"p{person}_{num}"] = cell["forms"]
            cell = lookup(candidate, pos="verb", form="infinitive", tense="present", voice=voice)
            if cell and cell["forms"]:
                table["infinitive"] = cell["forms"]
            if len(table) == 7:
                paradigms[voice] = table
        passive = request.get("passive", False)
        if "active" not in paradigms or (passive and "passive" not in paradigms):
            raise CacheError(f"Incomplete six-person paradigm: {candidate['id']}")
        return {"headword": forms[0], "infinitive": forms[1] if len(forms) > 1 else paradigms["active"]["infinitive"][0],
                "conjugation": "custom", "passive": passive, "quantities_known": quantities, "paradigms": paradigms}
    raise CacheError(f"No current quiz adapter for {pos}")


def approved_legacy_records(path=DEFAULT_CACHE):
    path = Path(path)
    if not path.exists():
        return {"nouns": {}, "adjectives": {}, "verbs": {}}
    stat = path.stat()
    return deepcopy(_approved_legacy_records(str(path.resolve()), stat.st_mtime_ns, stat.st_size))


@lru_cache(maxsize=8)
def _approved_legacy_records(path, modified, size):
    data = load_cache(path)
    records = {"nouns": {}, "adjectives": {}, "verbs": {}}
    for record in data["entries"].values():
        if record["status"] != "ready" or record.get("review_status") != "approved":
            continue
        request = record["request"]
        if request["pos"] not in ("noun", "adjective", "verb"):
            continue
        definition = legacy_record(request, record["candidate"])
        from vocab import normalize
        head = normalize(request["forms"][0])
        category = {"noun": "nouns", "adjective": "adjectives", "verb": "verbs"}[request["pos"]]
        if head in records[category] and records[category][head] != definition:
            raise CacheError(f"Approved homographs need an explicit legacy mapping: {head}")
        records[category][head] = definition
    return records
