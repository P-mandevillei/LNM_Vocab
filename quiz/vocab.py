"""Parsing and grading logic for the Latin vocab quiz.

Markdown format assumed (see ch1.md / ch2.md):

    **NOUNS**
    agricola, agricolae, m. - farmer

    **VERBS**
    amo, amare, amavi, amatum - to love

    **ADJECTIVES**
    magnus, magna, magnum - large

A line is a vocab entry if it contains a dash separator surrounded by
whitespace.  The part before the dash is a comma-separated list of Latin
forms; the part after is the English gloss (which may itself list several
meanings separated by commas or semicolons).

The heading decides how the forms are read -- genitive + gender for a noun,
principal parts for a verb, the gender set for an adjective or pronoun -- and
only the forms actually listed are ever asked about.
"""

from __future__ import annotations

import random
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# markdown parsing
# --------------------------------------------------------------------------

HEADER_RE = re.compile(r"^\s*(?:\*\*|__|#{1,6}\s*)(.+?)(?:\*\*|__)?\s*$")
BOLD_HEADER_RE = re.compile(r"^\s*(?:\*\*|__)(.+?)(?:\*\*|__)\s*$")
MD_HEADER_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
SPLIT_RE = re.compile(r"\s+[–—-]\s+")
GENDERS = {
    "m": "masculine",
    "f": "feminine",
    "n": "neuter",
    "c": "common",
}
PRONOUN_PREFIXES = (
    "he/she/it ",
    "he/she ",
    "i ",
    "you ",
    "we ",
    "they ",
    "it ",
    "s/he ",
)
CASES = ("nominative", "genitive", "dative", "accusative", "ablative",
         "vocative", "locative")
CASE_ABBREVS = {c: c[:3] for c in CASES}
# "____" in place of a principal part the chapter doesn't give.
PLACEHOLDER_RE = re.compile(r"^[_\-–—?~.\s]+$")
# "iussum + accusative + infinitive", "cum + ablative"
ANNOTATION_SPLIT_RE = re.compile(r"\s*\+\s*")
PAREN_RE = re.compile(r"\s*\(([^)]*)\)")


@dataclass
class Entry:
    latin_forms: list[str]        # real forms only; "____" placeholders dropped
    english: str                  # gloss as written, notes included
    pos: str                      # singular, lowercase: "noun", "verb", ...
    source: str                   # markdown file, relative to the vault
    line: int
    gender: str | None = None     # as written: "f.", "n. pl."
    number: str | None = None     # "pl" / "sg", when the gender says so
    annotation: str | None = None  # what followed a "+": "ablative"
    raw_latin: str = ""           # left-hand side exactly as written
    key: str = field(default="", repr=False)

    @property
    def headword(self) -> str:
        return self.latin_forms[0]

    @property
    def prompt_form(self) -> str:
        """What a Latin -> English question shows.

        Prepositions keep their case ("in + ablative"): the two `in` entries
        differ only in that, so dropping it would make the question unanswerable.
        """
        if self.annotation and self.pos == "preposition":
            return f"{self.headword} + {self.annotation}"
        return self.headword

    @property
    def english_core(self) -> str:
        """Gloss without parenthetical notes -- used for prompts and matching."""
        core = PAREN_RE.sub("", self.english).strip()
        core = re.sub(r"\s+", " ", core).strip(" ,;")
        return core or self.english


# Longest/most specific stems first: "adverb" contains "verb", and
# "pronoun" contains "noun".
POS_KEYWORDS = (
    ("adjectiv", "adjective"),
    ("adverb", "adverb"),
    ("pronoun", "pronoun"),
    ("preposition", "preposition"),
    ("conjunction", "conjunction"),
    ("interjection", "interjection"),
    ("participle", "participle"),
    ("numeral", "numeral"),
    ("number", "numeral"),
    ("noun", "noun"),
    ("verb", "verb"),
    ("phrase", "phrase"),
    ("idiom", "phrase"),
    ("expression", "phrase"),
)


# These never decline or conjugate, so a comma inside one is punctuation
# rather than a form boundary.
UNINFLECTED_POS = {"conjunction", "interjection", "phrase", "preposition"}


def _detect_pos(header: str) -> str:
    """"ADJECTIVES (1st/2nd declension)" -> "adjective"."""
    h = header.strip().lower()
    for stem, pos in POS_KEYWORDS:
        if stem in h:
            return pos

    # Unknown heading: clean it up and singularize naively.
    h = re.sub(r"[^a-z ]", " ", h)
    h = re.sub(r"\s+", " ", h).strip()
    if h.endswith("ies"):
        return h[:-3] + "y"
    if h.endswith("s") and not h.endswith("ss"):
        return h[:-1]
    return h or "word"


def _split_gender(token: str) -> tuple[list[str], str | None] | None:
    """"n. pl." -> (["n"], "pl");  "m."  -> (["m"], None);  "aquae" -> None."""
    t = strip_macrons(token).strip().lower()
    t = t.replace(" or ", "/")

    number = None
    m = re.search(r"\b(pl|plural|sg|sing|singular)\b\.?$", t)
    if m:
        number = "pl" if m.group(1).startswith("pl") else "sg"
        t = t[:m.start()].strip()

    parts = [p.strip().rstrip(".") for p in t.strip(". ").split("/")]
    parts = [p for p in parts if p]
    if not parts or not all(p in GENDERS for p in parts):
        return None
    return parts, number


def _is_gender(token: str) -> bool:
    return _split_gender(token) is not None


def _split_annotation(forms: list[str]) -> tuple[list[str], str | None]:
    """Pull "+ ablative" / "+ accusative + infinitive" off the Latin forms."""
    kept: list[str] = []
    notes: list[str] = []
    for form in forms:
        head, *rest = ANNOTATION_SPLIT_RE.split(form)
        head = head.strip()
        if head:
            kept.append(head)
        notes.extend(r.strip() for r in rest if r.strip())
    return kept, " + ".join(notes) or None


def parse_file(path: Path, vault: Path) -> list[Entry]:
    """Parse one markdown file into vocabulary entries."""
    rel = path.relative_to(vault).as_posix()
    entries: list[Entry] = []
    pos = "word"

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line in {"---", "***"}:
            continue

        m = BOLD_HEADER_RE.match(line) or MD_HEADER_RE.match(line)
        if m and not SPLIT_RE.search(line):
            pos = _detect_pos(m.group(1))
            continue

        line = re.sub(r"^[-*+]\s+", "", line)          # tolerate bullet lists
        parts = SPLIT_RE.split(line, maxsplit=1)
        if len(parts) != 2:
            continue

        latin_raw, english = parts[0].strip(), parts[1].strip()
        latin_raw = latin_raw.strip("*` ").strip()
        if not latin_raw or not english:
            continue

        gender = number = None
        if pos in UNINFLECTED_POS:
            # "non solum..., sed etiam..." is one expression, not two forms
            forms = [latin_raw]
        else:
            forms = [f.strip() for f in latin_raw.split(",") if f.strip()]
            if len(forms) > 1 and _is_gender(forms[-1]):
                gender = forms.pop().strip()
                number = _split_gender(gender)[1]

        forms, annotation = _split_annotation(forms)
        # "timeō, timēre, timuī, ____" -- the chapter gives no 4th part
        forms = [f for f in forms if not PLACEHOLDER_RE.match(f)]
        if not forms:
            continue

        entry = Entry(
            latin_forms=forms,
            english=english,
            pos=pos,
            source=rel,
            line=lineno,
            gender=gender,
            number=number,
            annotation=annotation,
            raw_latin=latin_raw,
        )
        entry.key = f"{rel}:{lineno}"
        entries.append(entry)

    return entries


def find_markdown_files(vault: Path) -> list[Path]:
    skip = {".obsidian", ".trash", ".git", "quiz"}
    out = []
    for p in sorted(vault.rglob("*.md")):
        if any(part in skip for part in p.relative_to(vault).parts[:-1]):
            continue
        if p.parent.name == "quiz":
            continue
        out.append(p)
    return out


def load_vault(vault: Path) -> dict[str, list[Entry]]:
    return {
        p.relative_to(vault).as_posix(): parse_file(p, vault)
        for p in find_markdown_files(vault)
    }


# --------------------------------------------------------------------------
# answer normalisation / comparison
# --------------------------------------------------------------------------

def strip_macrons(s: str) -> str:
    decomposed = unicodedata.normalize("NFD", s)
    return unicodedata.normalize(
        "NFC", "".join(c for c in decomposed if not unicodedata.combining(c))
    )


def normalize_keep(s: str) -> str:
    """Fold case and punctuation but keep macrons."""
    s = s.lower().replace("–", "-").replace("’", "'")
    s = re.sub(r"[^\w/'\- ]", " ", s).replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize(s: str) -> str:
    """Fold case, punctuation and macrons."""
    return normalize_keep(strip_macrons(s))


def variant_sets(variants: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split accepted spellings into macron-exact and macron-blind sets.

    Answers matching the first are right; answers matching only the second got
    the letters right but a macron wrong, which is worth pointing out.
    """
    strict = {normalize_keep(v) for v in variants}
    loose = {normalize(v) for v in variants}
    return sorted(v for v in loose if v), sorted(v for v in strict if v)


def _english_variants(english: str) -> set[str]:
    """All strings we are willing to accept for an English gloss.

    A parenthetical note ("to give (note the short stem vowel)") is optional,
    so both the full gloss and the bare meaning count.
    """
    variants = {english, PAREN_RE.sub("", english).strip()}
    for v in list(variants):
        variants.update(p.strip() for p in re.split(r"[;,]", v) if p.strip())
    for p in list(variants):
        low = p.lower().strip()
        if low.startswith("to "):
            variants.add(p[3:].strip())
        for pref in PRONOUN_PREFIXES:
            if low.startswith(pref):
                variants.add(p[len(pref):].strip())
    return {v for v in variants if v.strip()}


def _latin_variants(form: str) -> set[str]:
    """Accept "ē (ex)" as any of "ē (ex)", "ē" or "ex"."""
    out = {form, form.lstrip("-")}
    without = PAREN_RE.sub("", form).strip()
    if without:
        out.add(without)
    for inner in PAREN_RE.findall(form):
        if inner.strip():
            out.add(inner.strip())
    return {v for v in out if v.strip()}


def _gender_variants(gender: str) -> set[str]:
    split = _split_gender(gender)
    letters, number = split if split else ([], None)

    bases = {gender}
    for letter in letters:
        full = GENDERS.get(letter, letter)
        bases |= {letter, f"{letter}.", full, full[:4]}
    if len(letters) > 1:
        bases.add("/".join(letters))
        bases.add(" or ".join(letters))

    out = set(bases)
    if number:
        words = ["pl", "pl.", "plural"] if number == "pl" else ["sg", "sg.", "singular"]
        out |= {f"{b} {w}" for b in bases for w in words}
    return {v for v in out if v.strip()}


def _case_variants(annotation: str) -> set[str]:
    """Accept "abl", "abl." or "ablative" for a preposition's case."""
    out = {annotation}
    found = [c for c in CASES if c in strip_macrons(annotation).lower()]
    for case in found:
        out |= {case, CASE_ABBREVS[case], f"{CASE_ABBREVS[case]}."}
    if len(found) > 1:
        out.add(" or ".join(found))
        out.add("/".join(found))
        out.add(" ".join(CASE_ABBREVS[c] for c in found))
    return {v for v in out if v.strip()}


def check(given: str, accepted: set[str], strict: set[str]) -> str:
    """Return "correct", "macrons", or "wrong"."""
    given = (given or "").strip()
    if not given:
        return "wrong"
    if normalize_keep(given) in strict:
        return "correct"
    if normalize(given) in accepted:
        return "macrons"          # right letters, a macron off
    return "wrong"


# --------------------------------------------------------------------------
# question construction
# --------------------------------------------------------------------------

VERB_PART_LABELS = {
    1: "2nd principal part (infinitive)",
    2: "3rd principal part (1st sg. perfect)",
    3: "4th principal part (participle/supine)",
}
VERB_SHORT_LABELS = {
    1: "2nd p.p. (inf.)",
    2: "3rd p.p. (perf.)",
    3: "4th p.p.",
}
# Parts of speech whose extra forms are the masculine/feminine/neuter set.
GENDERED_POS = {"adjective", "pronoun", "participle", "numeral"}
DEGREE_LABELS = {1: "comparative", 2: "superlative"}
DEGREE_KEYS = {1: "comp", 2: "sup"}
DEGREE_SHORT = {1: "comp.", 2: "superl."}


def _field(key: str, label: str, short: str, answer: str,
           variants: set[str]) -> dict:
    accepted, strict = variant_sets(variants)
    return {
        "key": key,
        "label": label,
        "short": short,
        "answer": answer,
        "accepted": accepted,
        "strict": strict,
    }


def _latin_field(key: str, label: str, short: str, form: str) -> dict:
    return _field(key, label, short, form, _latin_variants(form))


def _gender_field(gender: str) -> dict:
    return _field("gender", "gender (m. / f. / n.)", "gender", gender,
                  _gender_variants(gender))


def _looks_neuter(form: str) -> bool:
    """Tell a 2-termination adjective (omnis, omne) from a 1-termination one
    (fēlīx, fēlīcis), whose second form is a genitive rather than a neuter."""
    f = strip_macrons(form).lower()
    return f.endswith("e") and not f.endswith("ae")


def parse_fields(entry: Entry, direction: str = "la_to_en") -> list[dict]:
    """The word-parsing sub-questions appropriate to this entry, if any.

    Only forms *other than* the headword are asked -- the headword is already
    either the prompt or the main answer -- and only forms the chapter actually
    lists, so a missing 4th principal part is never asked for.
    """
    fields: list[dict] = []
    extra = entry.latin_forms[1:]
    pos = entry.pos

    if pos == "noun":
        if extra:
            plural = entry.number == "pl"
            fields.append(_latin_field(
                "gen",
                "genitive plural" if plural else "genitive singular",
                "gen. pl." if plural else "gen. sg.",
                extra[0]))
        for i, form in enumerate(extra[1:], start=2):
            fields.append(_latin_field(f"form{i + 1}", f"form {i + 1}",
                                       f"form {i + 1}", form))

    elif pos == "verb":
        # Plenty of verbs list only three parts (no supine) or two; label by
        # position so the missing 4th part is simply never asked.
        for i, part in enumerate(extra, start=1):
            label = VERB_PART_LABELS.get(i, f"principal part {i + 1}")
            fields.append(_latin_field(f"pp{i + 1}", label,
                                       VERB_SHORT_LABELS.get(i, f"p.p. {i + 1}"),
                                       part))

    elif pos in GENDERED_POS:
        # adjectives / pronouns: a 3-form listing is the m./f./n. set
        if len(extra) == 2:
            fields.append(_latin_field("fem", "feminine", "fem.", extra[0]))
            fields.append(_latin_field("neut", "neuter", "neut.", extra[1]))
        elif len(extra) == 1 and _looks_neuter(extra[0]):
            fields.append(_latin_field("neut", "neuter", "neut.", extra[0]))
        elif len(extra) == 1:
            fields.append(_latin_field("gen", "genitive singular", "gen. sg.",
                                       extra[0]))
        else:
            for i, form in enumerate(extra, start=1):
                fields.append(_latin_field(f"form{i + 1}", f"form {i + 1}",
                                           f"form {i + 1}", form))

    elif pos == "adverb":
        # bene, melius, optimē -- positive, comparative, superlative
        for i, form in enumerate(extra, start=1):
            label = DEGREE_LABELS.get(i, f"form {i + 1}")
            fields.append(_latin_field(DEGREE_KEYS.get(i, f"form{i + 1}"),
                                       label,
                                       DEGREE_SHORT.get(i, f"form {i + 1}"),
                                       form))

    else:
        for i, form in enumerate(extra, start=1):
            fields.append(_latin_field(f"form{i + 1}", f"form {i + 1}",
                                       f"form {i + 1}", form))

    if entry.gender:
        fields.append(_gender_field(entry.gender))

    # A preposition's case is worth asking -- but only when the prompt is the
    # English meaning, since prompt_form spells it out in the other direction.
    if pos == "preposition" and entry.annotation and direction == "en_to_la":
        fields.append(_field("case", "case it takes", "case", entry.annotation,
                             _case_variants(entry.annotation)))

    return fields


def _full_latin(entry: Entry) -> str:
    """The Latin side exactly as the chapter writes it."""
    if entry.raw_latin:
        return entry.raw_latin
    s = ", ".join(entry.latin_forms)
    if entry.gender:
        s += f", {entry.gender}"
    return s


def select_entries(pool: list[Entry], count: int, exhaustive: bool = False,
                   shuffle: bool = True,
                   rng: random.Random | None = None) -> list[Entry]:
    """Choose the words a sheet will cover.

    exhaustive: every word in the pool exactly once (`count` is ignored),
    either shuffled or in the order the markdown files list them.
    """
    rng = rng or random.Random()
    if not pool:
        return []

    if exhaustive:
        chosen = list(pool)
        if shuffle:
            rng.shuffle(chosen)
        return chosen

    if count <= len(pool):
        chosen = rng.sample(pool, count)
    else:                                     # more questions than words: repeat
        chosen = rng.sample(pool, len(pool))
        chosen += rng.choices(pool, k=count - len(pool))
        rng.shuffle(chosen)
    return chosen


def make_questions(chosen: list[Entry], twin_pool: list[Entry], mode: str,
                   include_parsing: bool, rng: random.Random | None = None,
                   directions: dict[str, str] | None = None) -> list[dict]:
    """Turn chosen entries into questions.

    twin_pool is the vocabulary an English -> Latin answer may come from, so a
    gloss shared by two words accepts either.  directions pins a question to a
    direction by entry key -- a retest asks the way you got it wrong.
    """
    rng = rng or random.Random()
    directions = directions or {}

    by_english: dict[str, list[Entry]] = {}
    for e in twin_pool:
        by_english.setdefault(normalize(e.english_core), []).append(e)

    questions = []
    for i, entry in enumerate(chosen):
        direction = directions.get(entry.key) or (
            rng.choice(["la_to_en", "en_to_la"]) if mode == "mixed" else mode)

        if direction == "la_to_en":
            prompt, prompt_label = entry.prompt_form, "Give the English meaning"
            variants = _english_variants(entry.english)
            answer = entry.english
        else:
            prompt, prompt_label = entry.english_core, "Give the Latin word"
            twins = by_english.get(normalize(entry.english_core), [entry])
            variants = set()
            heads = []
            for t in twins:
                variants |= _latin_variants(t.headword)
                heads.append(t.headword)
                # writing out the whole listing ("magnus, magna, magnum") counts
                variants |= {", ".join(t.latin_forms), _full_latin(t),
                             t.prompt_form}
            answer = " / ".join(dict.fromkeys(heads))

        accepted, strict = variant_sets(variants)
        fields = parse_fields(entry, direction) if include_parsing else []

        questions.append({
            "index": i,
            "direction": direction,
            "prompt": prompt,
            "prompt_label": prompt_label,
            "pos": entry.pos,
            "source": entry.source,
            "entry_key": entry.key,
            "answer": answer,
            "accepted": accepted,
            "strict": strict,
            "fields": fields,
            "full_entry": f"{_full_latin(entry)} – {entry.english}",
        })

    return questions


def build_quiz(pool: list[Entry], count: int, mode: str, include_parsing: bool,
               rng: random.Random | None = None, exhaustive: bool = False,
               shuffle: bool = True) -> list[dict]:
    rng = rng or random.Random()
    if not pool:
        return []
    chosen = select_entries(pool, count, exhaustive, shuffle, rng)
    return make_questions(chosen, pool, mode, include_parsing, rng)


def grade(questions: list[dict], answers: list[dict]) -> dict:
    """answers[i] = {"main": str, "fields": {key: str}}"""
    results = []
    main_correct = 0
    field_total = field_correct = 0

    for q in questions:
        given = answers[q["index"]] if q["index"] < len(answers) else {}
        main_given = (given.get("main") or "").strip()
        verdict = check(main_given, set(q["accepted"]), set(q["strict"]))
        if verdict in ("correct", "macrons"):
            main_correct += 1

        field_results = []
        for f in q["fields"]:
            fg = (given.get("fields", {}).get(f["key"]) or "").strip()
            fv = check(fg, set(f["accepted"]), set(f["strict"]))
            field_total += 1
            if fv in ("correct", "macrons"):
                field_correct += 1
            field_results.append({
                "label": f["label"],
                "given": fg,
                "answer": f["answer"],
                "verdict": fv,
            })

        results.append({
            "index": q["index"],
            "direction": q["direction"],
            "prompt": q["prompt"],
            "prompt_label": q["prompt_label"],
            "pos": q["pos"],
            "source": q["source"],
            "given": main_given,
            "answer": q["answer"],
            "verdict": verdict,
            "fields": field_results,
            "full_entry": q["full_entry"],
        })

    missed = missed_entries(questions, results)
    return {
        "results": results,
        "score": {
            "main_correct": main_correct,
            "main_total": len(questions),
            "field_correct": field_correct,
            "field_total": field_total,
            "missed": len(missed),
        },
        "missed": missed,
    }


def is_mistake(result: dict) -> bool:
    """A missing or wrong macron is not a mistake worth retesting."""
    return (result["verdict"] == "wrong"
            or any(f["verdict"] == "wrong" for f in result["fields"]))


def missed_entries(questions: list[dict],
                   results: list[dict]) -> list[dict]:
    """The words to retest: {"key", "direction"}, each word only once."""
    missed: dict[str, dict] = {}
    for q, r in zip(questions, results):
        if is_mistake(r) and q["entry_key"] not in missed:
            missed[q["entry_key"]] = {"key": q["entry_key"],
                                      "direction": q["direction"]}
    return list(missed.values())
