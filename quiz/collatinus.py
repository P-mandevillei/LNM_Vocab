"""Build-time Collatinus client. Never used by quiz/grading request handlers."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
import ssl
import time
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ENDPOINT = "https://outils.biblissima.fr/collatinus-web/collatinus-web.php"
PROVIDER = "collatinus-biblissima"
PARSER_VERSION = 2
SOURCE = "https://outils.biblissima.fr/en/collatinus-web/index.php"


def tls_context():
    """Use native trust when installed, always retaining certificate verification."""
    try:
        import truststore
    except ImportError:
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class ProviderError(ValueError):
    pass


CASES = {"nominatif": "nominative", "vocatif": "vocative", "accusatif": "accusative",
         "génitif": "genitive", "datif": "dative", "ablatif": "ablative"}
GENDERS = {"masculin": "m", "féminin": "f", "neutre": "n"}
NUMBERS = {"singulier": "singular", "pluriel": "plural"}
TENSES = {"présent": "present", "imparfait": "imperfect", "futur": "future",
          "parfait": "perfect", "plus-que-parfait": "pluperfect", "futur antérieur": "future_perfect"}
DEGREES = {"positif": "positive", "comparatif": "comparative", "superlatif": "superlative"}


def clean(text):
    return " ".join(text.replace("\xa0", " ").split())


def unmarked(text):
    text = "".join(c for c in unicodedata.normalize("NFD", clean(text)) if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", text).translate(str.maketrans({"æ": "ae", "œ": "oe", "Æ": "Ae", "Œ": "Oe"}))


def dictionary_spelling(text):
    return unmarked(text).lower().replace("j", "i")


def quantified(text):
    # Keep the provider's long marks for the audit, without interpreting them
    # as textbook vowel quantities. Some mark syllables long by position.
    return unicodedata.normalize("NFC", "".join(c for c in unicodedata.normalize("NFD", text) if c != "\u0306"))


def feature_key(features):
    return "|".join(f"{key}={value}" for key, value in sorted(features.items()))


class TableDocument(HTMLParser):
    """Read ordered headings, anchors and tables, including malformed <p>s."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events = []
        self.capture = None
        self.text = []
        self.links = []
        self.link = None
        self.table = None
        self.row = None
        self.cell = None

    def flush(self):
        if self.capture:
            self.events.append((self.capture, "".join(self.text), self.links))
        self.capture, self.text, self.links = None, [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self.flush()
            if self.table is not None:
                raise ProviderError("Unexpected nested table")
            self.table = []
        elif self.table is not None:
            if tag == "tr":
                self.row = []
            elif tag in ("td", "th"):
                self.cell = []
            elif tag == "br" and self.cell is not None:
                self.cell.append(" ")
        elif tag in ("h4", "h5", "p"):
            self.flush()
            self.capture = tag
        elif tag == "a":
            if "name" in attrs:
                self.flush()
                self.events.append(("anchor", attrs["name"], []))
            if self.capture == "h4" and attrs.get("href", "").startswith("#"):
                self.link = [attrs["href"][1:], []]
        elif tag == "br" and self.capture:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if self.table is not None:
            if tag in ("td", "th") and self.cell is not None:
                self.row.append(clean("".join(self.cell)))
                self.cell = None
            elif tag == "tr" and self.row is not None:
                self.table.append(self.row)
                self.row = None
            elif tag == "table":
                self.events.append(("table", self.table, []))
                self.table = None
        elif tag == "a" and self.link is not None:
            self.links.append((self.link[0], clean("".join(self.link[1]))))
            self.link = None
        elif tag == self.capture:
            self.flush()

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        elif self.capture:
            self.text.append(data)
        elif self.table is None and clean(data).lower() in NUMBERS:
            # Pronoun number headings are loose text outside paragraph tags.
            self.events.append(("p", clean(data).lower(), []))
        if self.link is not None:
            self.link[1].append(data)


def add_cell(candidate, features, text):
    raw = [clean(form.strip(" ()")) for form in text.split(",")]
    raw = list(dict.fromkeys(form for form in raw if form and form not in ("-", "—")))
    if any("⋮" in form or "/" in form for form in raw):
        candidate["unparsed"].append({"reason": "Abbreviated form", "features": features, "text": text})
        return
    spellings = [unmarked(f) for f in raw]
    # The source uses consonantal j where the textbook uses i. Retain both
    # spellings as source variants, rather than confusing them with homographs.
    spellings += [f.replace("j", "i").replace("J", "I") for f in spellings if "j" in f.lower()]
    cell = {"features": features, "forms": list(dict.fromkeys(spellings)),
            "source_forms": raw, "status": "available" if raw else "unavailable"}
    key = feature_key(features)
    previous = candidate["cells"].get(key)
    if previous and previous != cell:
        raise ProviderError(f"Conflicting duplicate cell: {candidate['id']}: {key}")
    candidate["cells"][key] = cell
    if features["pos"] not in candidate["kinds"]:
        candidate["kinds"].append(features["pos"])


def parse_table(candidate, rows, context):
    if not rows:
        return
    header = [clean(c).lower() for c in rows[0]]
    if header == ["cas", "singulier", "pluriel"]:
        for row in rows[1:]:
            if len(row) != 3 or row[0] not in CASES:
                raise ProviderError("Unexpected noun table row")
            for number, text in zip(NUMBERS.values(), row[1:]):
                add_cell(candidate, {"pos": "noun", "case": CASES[row[0]], "number": number}, text)
    elif header == ["positif", "comparatif", "superlatif"]:
        if len(rows) != 2 or len(rows[1]) != 3:
            raise ProviderError("Malformed adverb degree table")
        for degree, text in zip(DEGREES.values(), rows[1]):
            add_cell(candidate, {"pos": "adverb", "degree": degree}, text)
    elif (any(c in DEGREES for c in header) or any(len(r) > 1 and r[1].strip() in DEGREES for r in rows)):
        number, degrees = None, None
        gender = context["gender"]
        if not gender:
            raise ProviderError("Adjective table has no gender heading")
        for row in rows:
            if len(row) == 1 and row[0] in NUMBERS:
                number = NUMBERS[row[0]]
            elif row and row[0] == "cas":
                degrees = [DEGREES.get(c.strip()) for c in row[1:]]
                if not all(degrees):
                    raise ProviderError("Unknown adjective degree")
            elif row and row[0] in CASES:
                if not number or not degrees or len(row) != len(degrees) + 1:
                    raise ProviderError("Malformed adjective table")
                for degree, text in zip(degrees, row[1:]):
                    add_cell(candidate, {"pos": "adjective", "case": CASES[row[0]], "number": number,
                                         "gender": gender, "degree": degree}, text)
    elif header == ["cas", "masculin", "féminin", "neutre"]:
        number = context.get("number")
        section = context.get("section")
        pos = "verb" if section else "pronoun"
        for row in rows[1:]:
            if len(row) == 1 and row[0] in NUMBERS:
                number = NUMBERS[row[0]]
            elif row and row[0] in CASES:
                if not number or len(row) != 4:
                    raise ProviderError("Malformed gendered table")
                for gender, text in zip(GENDERS.values(), row[1:]):
                    features = {"pos": pos, "case": CASES[row[0]], "number": number, "gender": gender}
                    if section:
                        features.update(section)
                    add_cell(candidate, features, text)
    elif header == ["personne", "singulier", "pluriel"]:
        for row in rows[1:]:
            match = re.fullmatch(r"([23])ème (pr\.|fut\.)", row[0]) if row else None
            if not match or len(row) != 3:
                raise ProviderError("Malformed imperative table")
            for number, text in zip(NUMBERS.values(), row[1:]):
                add_cell(candidate, {"pos": "verb", "mood": "imperative", "voice": context["voice"],
                                     "tense": "present" if match[2] == "pr." else "future",
                                     "person": int(match[1]), "number": number}, text)
    elif header and all(h in TENSES for h in header):
        if len(rows) != 7:
            candidate["unparsed"].append({"reason": "Abbreviated finite paradigm", "context": dict(context), "rows": rows})
            return
        if context["mood"] not in ("indicative", "subjunctive"):
            raise ProviderError("Finite paradigm has no mood")
        for index, row in enumerate(rows[1:]):
            if len(row) != len(header):
                raise ProviderError("Malformed finite paradigm")
            for tense, text in zip(header, row):
                add_cell(candidate, {"pos": "verb", "mood": context["mood"], "voice": context["voice"],
                                     "tense": TENSES[tense], "person": index % 3 + 1,
                                     "number": "singular" if index < 3 else "plural"}, text)
    elif all(len(row) == 2 and (row[0].startswith("gérondif ") or row[0].startswith("supin ")) for row in rows):
        for label, text in rows:
            case = CASES.get(label.split()[-1]) if label.startswith("gérondif") else (
                "accusative" if label.endswith("-um") else "ablative")
            if not case:
                raise ProviderError("Unknown gerund case")
            add_cell(candidate, {"pos": "verb", "form": "gerund" if label.startswith("gérondif") else "supine", "case": case}, text)
    else:
        candidate["unparsed"].append({"reason": "Unrecognized table layout", "context": dict(context), "rows": rows})


def parse_response(content: bytes) -> list[dict]:
    if not content.strip():
        return []
    document = TableDocument()
    document.feed(content.decode("utf-8-sig"))
    document.flush()
    candidates, current = {}, None
    context = {"voice": "active", "mood": None, "gender": None, "number": None, "section": None}
    for tag, value, links in document.events:
        if tag == "h4" and links:
            lines = value.splitlines()
            for identity, head in links:
                candidates.setdefault(identity, {"id": identity, "headword": unmarked(head),
                    "source_headword": head, "description": next((clean(line) for line in lines if head in line), clean(value)),
                    "kinds": [], "cells": {}, "unparsed": []})
        elif tag == "anchor" and value in candidates:
            if current is not candidates[value]:
                context = {"voice": "active", "mood": None, "gender": None, "number": None, "section": None}
                current = candidates[value]
        elif tag == "table" and current:
            parse_table(current, value, context)
        elif tag in ("p", "h4", "h5"):
            text = clean(value).lower()
            if text in ("actif", "passif"):
                context["voice"] = "active" if text == "actif" else "passive"
            elif text in GENDERS:
                context["gender"] = GENDERS[text]
            elif text in NUMBERS:
                context["number"] = NUMBERS[text]
            elif text.startswith("indicatif"):
                context.update(mood="indicative", section=None)
            elif text == "subjonctif":
                context.update(mood="subjunctive", section=None)
            elif text == "impératif":
                context.update(mood="imperative", section=None)
            elif text.startswith("participe "):
                tense = TENSES.get(text.split()[-1])
                if tense:
                    context["section"] = {"form": "participle", "tense": tense,
                                          "voice": "passive" if tense == "perfect" else "active"}
            elif text == "adjectif verbal":
                context["section"] = {"form": "gerundive", "voice": "passive"}
            if current:
                for tense, voice, form in re.findall(r"infinitif (présent|parfait|futur) (actif|passif)\s*:\s*([^\n]+)", value, re.I):
                    add_cell(current, {"pos": "verb", "form": "infinitive", "tense": TENSES[tense.lower()],
                                       "voice": "active" if voice.lower() == "actif" else "passive"}, form)
    if not candidates:
        raise ProviderError("Response contains no identifiable lemma menu (not a valid inflection response)")
    for candidate in candidates.values():
        candidate["cells"] = dict(sorted(candidate["cells"].items()))
    return list(candidates.values())


class CollatinusClient:
    def __init__(self, endpoint=ENDPOINT, timeout=30, delay=1.0):
        self.endpoint = endpoint
        self.timeout = timeout
        self.delay = delay
        self.last_request = 0.0
        self.requests = 0
        self.context = tls_context()

    def fetch(self, word: str) -> bytes:
        if not word.strip() or any(char.isspace() for char in word.strip()):
            raise ProviderError("Collatinus lookup requires a single word.")
        remaining = self.delay - (time.monotonic() - self.last_request)
        if remaining > 0:
            time.sleep(remaining)
        request = Request(self.endpoint, urlencode({"opera": "flexion", "lemme": word}).encode(),
                          headers={"User-Agent": "LatinVocabMorphologyImporter/1.0",
                                   "Accept": "text/html; charset=utf-8"})
        self.last_request = time.monotonic()
        self.requests += 1
        with urlopen(request, timeout=self.timeout, context=self.context) as response:
            content = response.read(4_000_001)
        if len(content) > 4_000_000:
            raise ProviderError("Provider response exceeded the size limit.")
        return content


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Save one Collatinus response for inspection")
    parser.add_argument("word")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = CollatinusClient().fetch(args.word)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print(f"Saved {len(data)} bytes to {args.output}")
