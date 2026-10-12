"""Validated, reloadable lexical data for morphology answer generation.

Bundled vocabulary is supplemented or overridden by morphology.json in the
selected vault. This module deliberately has no dependency on the quiz UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

import vocab

CASES = ("nominative", "genitive", "dative", "accusative", "ablative", "vocative")
NUMBERS = ("singular", "plural")
GENDERS = {"m": "masculine", "f": "feminine", "n": "neuter"}
NOMINAL_KEYS = {f"{case}_{number}" for case in CASES for number in NUMBERS}
VERB_KEYS = {f"p{p}_{number}" for p in range(1, 4) for number in NUMBERS} | {"infinitive"}
HERE = Path(__file__).resolve().parent


class LexiconError(ValueError):
    """A definition is malformed; do not use it as an answer key."""


@dataclass(frozen=True)
class Nominal:
    forms: tuple[str, ...]
    genders: tuple[str, ...]
    declension: int
    number: str | None = None
    i_stem: bool | None = False
    quantities_known: bool = True
    stem: str | None = None
    pos: str = "noun"
    pronominal: bool = False
    overrides: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Verb:
    head: str
    infinitive: str
    conjugation: str
    passive: bool = True
    quantities_known: bool = True
    stem: str | None = None
    paradigms: dict = field(default_factory=dict)
    overrides: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Lexicon:
    nouns: dict[str, Nominal]
    adjectives: dict[str, Nominal]
    verbs: dict[str, Verb]
    verb_aliases: dict[str, str]


def _fail(where: str, message: str):
    raise LexiconError(f"{where}: {message}")


def _text(value, where):
    if not isinstance(value, str) or not value.strip():
        _fail(where, "expected a nonempty string")
    return value.strip()


def _boolean(record, key, default, where):
    value = record.get(key, default)
    if not isinstance(value, bool):
        _fail(where, f"{key} must be true or false")
    return value


def _forms(value, where):
    if value is None:
        return None
    if isinstance(value, str):
        return [_text(value, where)]
    if not isinstance(value, list) or not value:
        _fail(where, "use a form, a nonempty list of accepted forms, or null for an unavailable form")
    return list(dict.fromkeys(_text(form, where) for form in value))


def _table(value, allowed, where, required=(), allow_null=True):
    if not isinstance(value, dict):
        _fail(where, "expected an object of form keys and answers")
    unknown = set(value) - allowed
    if unknown:
        _fail(where, f"unknown form keys: {', '.join(sorted(unknown))}")
    missing = set(required) - set(value)
    if missing:
        _fail(where, f"missing form keys: {', '.join(sorted(missing))}")
    result = {key: _forms(forms, f"{where}.{key}") for key, forms in value.items()}
    if not allow_null and any(forms is None for forms in result.values()):
        _fail(where, "a six-person verb paradigm and infinitive must have answers in all seven fields")
    return result


def _nominal(record, pos, where):
    allowed = {"forms", "gender", "declension", "number", "i_stem", "quantities_known",
               "stem", "pronominal", "overrides", "source"}
    if set(record) - allowed:
        _fail(where, f"unknown settings: {', '.join(sorted(set(record) - allowed))}")
    forms = record.get("forms", [])
    if not isinstance(forms, list) or (forms and len(forms) not in ((2,) if pos == "noun" else (2, 3))):
        _fail(where, "forms must contain a nominative/genitive pair or the adjective's two/three dictionary forms")
    forms = tuple(_text(form, f"{where}.forms") for form in forms)
    decl = record.get("declension")
    if (type(decl) not in (int, str)
            or decl not in ((1, 2, 3, 4, 5, "custom") if pos == "noun" else (2, 3, "custom"))):
        _fail(where, "choose a supported declension or 'custom'")
    gender = record.get("gender", "" if pos == "noun" else "m/f/n")
    if not isinstance(gender, str) or (gender and any(g not in GENDERS for g in gender.split("/"))):
        _fail(where, "gender must use m, f, n, or slash-separated combinations")
    genders = tuple(dict.fromkeys(gender.split("/"))) if gender else ()
    number = record.get("number")
    if number not in (None, "sg", "pl"):
        _fail(where, "number must be 'sg', 'pl', or null")
    i_stem = (_boolean(record, "i_stem", False, where) if "i_stem" in record or pos == "noun"
              else None if decl == 3 else False)
    quantities = _boolean(record, "quantities_known", bool(forms), where)
    stem = _text(record["stem"], where) if "stem" in record else None
    pronominal = _boolean(record, "pronominal", False, where)
    if pronominal and (pos != "adjective" or decl != 2):
        _fail(where, "pronominal applies only to first/second-declension adjectives")
    available_keys = {key for key in NOMINAL_KEYS
                      if number is None or key.endswith("plural" if number == "pl" else "singular")}
    required = available_keys if decl == "custom" else set()
    overrides = record.get("overrides", {})
    if pos == "adjective":
        if not isinstance(overrides, dict) or set(overrides) - set(GENDERS):
            _fail(where, "adjective overrides must be grouped by m, f and n")
        if decl == "custom" and set(overrides) != set(GENDERS):
            _fail(where, "a custom adjective needs complete tables for m, f and n")
        overrides = {g: _table(table, NOMINAL_KEYS, f"{where}.overrides.{g}", required)
                     for g, table in overrides.items()}
    else:
        overrides = _table(overrides, NOMINAL_KEYS, f"{where}.overrides", required)
    for table in (overrides.values() if pos == "adjective" else (overrides,)):
        if available_keys.issubset(table) and not any(table[key] for key in available_keys):
            _fail(where, "at least one nominal cell must have an answer")
    return Nominal(forms, genders, 0 if decl == "custom" else decl, number, i_stem,
                   quantities, stem, pos, pronominal, overrides)


def _verb(record, where):
    allowed = {"headword", "infinitive", "conjugation", "passive", "quantities_known",
               "stem", "aliases", "paradigms", "overrides", "source"}
    if set(record) - allowed:
        _fail(where, f"unknown settings: {', '.join(sorted(set(record) - allowed))}")
    head = _text(record["headword"], where) if "headword" in record else ""
    inf = _text(record["infinitive"], where) if "infinitive" in record else ""
    conj = str(record.get("conjugation", ""))
    if conj not in ("1", "2", "3", "3io", "4", "custom"):
        _fail(where, "conjugation must be 1, 2, 3, '3io', 4 or 'custom'")
    passive = _boolean(record, "passive", False, where)
    quantities = _boolean(record, "quantities_known", bool(head and inf), where)
    stem = _text(record["stem"], where) if "stem" in record else None
    parsed = {}
    for name in ("paradigms", "overrides"):
        tables = record.get(name, {})
        if not isinstance(tables, dict) or set(tables) - {"active", "passive"}:
            _fail(where, f"{name} must be grouped by 'active' and/or 'passive'")
        if name == "paradigms" and conj == "custom":
            for voice in (("active", "passive") if passive else ("active",)):
                if voice not in tables:
                    _fail(where, f"custom conjugation needs a complete {voice} paradigm")
        parsed[name] = {voice: _table(table, VERB_KEYS, f"{where}.{name}.{voice}",
                                     VERB_KEYS if name == "paradigms" else (), allow_null=False)
                        for voice, table in tables.items()}
    return Verb(head, inf, conj, passive, quantities, stem, parsed["paradigms"], parsed["overrides"])


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise LexiconError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _read(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique)
    except (ValueError, OSError) as exc:
        raise LexiconError(f"{path}: {exc}") from exc
    if not isinstance(data, dict) or type(data.get("version")) is not int or data.get("version") != 1:
        _fail(str(path), "expected an object with version: 1")
    if set(data) - {"version", "$schema", "nouns", "adjectives", "verbs"}:
        _fail(str(path), "only nouns, adjectives and verbs categories are supported")
    return data


def _merge(base, patch):
    result = dict(base)
    for key, value in patch.items():
        result[key] = _merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def load_lexicon(vault: Path | None = None, *, include_custom=True) -> Lexicon:
    """Read once per new draw, so changes apply without restarting the server."""
    paths = [HERE / "morphology_lexicon.json"]
    custom = (vault if vault is not None else HERE.parent) / "morphology.json"
    if include_custom and custom.exists():
        paths.append(custom)
    records = {"nouns": {}, "adjectives": {}, "verbs": {}}
    locations = {}
    for path in paths:
        data = _read(path)
        for category in records:
            additions = data.get(category, {})
            if not isinstance(additions, dict):
                _fail(str(path), f"{category} must be an object keyed by headword")
            seen = set()
            for head, record in additions.items():
                key = vocab.normalize(_text(head, str(path)))
                where = f"{path}: {category}.{head}"
                if key in seen:
                    _fail(where, "duplicate headword after case/macron normalization")
                seen.add(key)
                if not isinstance(record, dict):
                    _fail(where, "expected an object of lexical settings")
                records[category][key] = _merge(records[category].get(key, {}), record)
                locations[category, key] = where
    nouns = {key: _nominal(rec, "noun", locations["nouns", key]) for key, rec in records["nouns"].items()}
    adjectives = {key: _nominal(rec, "adjective", locations["adjectives", key])
                  for key, rec in records["adjectives"].items()}
    verbs = {key: _verb(rec, locations["verbs", key]) for key, rec in records["verbs"].items()}
    for category, models in (("nouns", nouns), ("adjectives", adjectives), ("verbs", verbs)):
        for key, model in models.items():
            head = model.head if category == "verbs" else model.forms[0] if model.forms else ""
            if head and vocab.normalize(head) != key:
                _fail(locations[category, key], "dictionary headword does not match the entry's key")
    aliases = {}
    for key, rec in records["verbs"].items():
        extra = rec.get("aliases", [])
        if not isinstance(extra, list):
            _fail(locations["verbs", key], "aliases must be a list of word forms")
        if extra and not verbs[key].head:
            _fail(locations["verbs", key], "aliases require an explicit headword")
        for alias in extra:
            alias = vocab.normalize(_text(alias, locations["verbs", key]))
            if alias in aliases or (alias in verbs and alias != key):
                _fail(locations["verbs", key], f"ambiguous verb alias: {alias}")
            aliases[alias] = key
    return Lexicon(nouns, adjectives, verbs, aliases)
