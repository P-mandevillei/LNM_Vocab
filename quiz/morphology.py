"""Local, deterministic answer keys for the morphology quiz.

Bundled and user-defined lexical data supply quantities and exceptions which
cannot be recovered from unmacronized chapter notes. Regular inflection rules
follow Allen & Greenough (see README.md). No network or model is used to grade.
Unknown inflection classes are reported as unavailable, never guessed.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from itertools import product
import random

import vocab
from morphology_data import (CASES, NUMBERS, GENDERS, Lexicon, Nominal, Verb,
                             load_lexicon)

KINDS = ("noun", "adjective", "verb", "pair")


class Unavailable(ValueError):
    """An entry does not have enough verified information for an answer key."""


# Compatibility names for the bundled data; new quizzes load vault overrides.
_DEFAULT_LEXICON = load_lexicon(include_custom=False)
NOUNS = _DEFAULT_LEXICON.nouns
ADJECTIVES = _DEFAULT_LEXICON.adjectives
VERBS = _DEFAULT_LEXICON.verbs
VERB_ALIASES = _DEFAULT_LEXICON.verb_aliases


def noun_model(entry: vocab.Entry, lexicon: Lexicon | None = None) -> Nominal:
    lexicon = lexicon or load_lexicon()
    if entry.pos != "noun":
        raise Unavailable("Needs a noun dictionary entry.")
    known = lexicon.nouns.get(vocab.normalize(entry.headword))
    parsed_gender = vocab._split_gender(entry.gender) if entry.gender else None
    genders = tuple(g for g in parsed_gender[0] if g in GENDERS) if parsed_gender else ()
    if known:
        if known.forms and len(entry.latin_forms) > 1 and vocab.normalize(entry.latin_forms[1]) != vocab.normalize(known.forms[1]):
            raise Unavailable("The listed genitive differs from morphology.json's dictionary entry.")
        if entry.number and known.number and entry.number != known.number:
            raise Unavailable("The number restriction conflicts with the reviewed dictionary forms.")
        model = replace(known, forms=known.forms or tuple(entry.latin_forms),
                        genders=known.genders or genders, number=known.number or entry.number)
        if not model.genders or (model.declension and len(model.forms) != 2):
            raise Unavailable("Add the missing dictionary forms and gender in morphology.json.")
        return model
    if len(entry.latin_forms) != 2 or not genders:
        raise Unavailable("Needs nominative, genitive and gender, or a definition in morphology.json.")
    head, gen = entry.latin_forms
    plain = vocab.normalize(gen)
    decl = 1 if plain.endswith("ae") or (entry.number == "pl" and plain.endswith("arum")) else 0
    if plain.endswith("i") or (entry.number == "pl" and plain.endswith("orum")):
        decl = 2
    if plain.endswith("us") or (entry.number == "pl" and plain.endswith("uum")):
        decl = 4
    if plain.endswith("ei"):
        decl = 5
    if not decl or any(" " in f for f in entry.latin_forms):
        raise Unavailable("Specify this noun's declension and i_stem setting in morphology.json.")
    plain_head = vocab.normalize(head)
    if decl == 1 and not plain_head.endswith("ae" if entry.number == "pl" else "a"):
        raise Unavailable("This nominative needs an exception definition in morphology.json.")
    if decl == 2 and entry.number != "pl" and not plain_head.endswith(("us", "um", "er", "ir")):
        raise Unavailable("This nominative needs an exception definition in morphology.json.")
    if plain_head in {"deus", "genius", "domus", "artus", "lacus", "partus", "tribus", "portus", "specus", "pecu", "acus"} or (
            decl == 2 and "n" in genders and not plain_head.endswith("um") and entry.number != "pl"):
        raise Unavailable("This noun needs lexical exceptions in morphology.json.")
    if decl == 4 and not plain_head.endswith(("us", "u")):
        raise Unavailable("This fourth-declension nominative needs a definition in morphology.json.")
    if decl == 5 and not plain_head.endswith("es"):
        raise Unavailable("This fifth-declension nominative needs a definition in morphology.json.")
    number = entry.number or ("sg" if decl == 5 and plain_head not in {"res", "dies"} else None)
    return Nominal(tuple(entry.latin_forms), genders, decl, number, quantities_known=False)


def adjective_model(entry: vocab.Entry, lexicon: Lexicon | None = None) -> Nominal:
    lexicon = lexicon or load_lexicon()
    if entry.pos != "adjective":
        raise Unavailable("Needs an adjective dictionary entry.")
    forms = tuple(entry.latin_forms)
    known = lexicon.adjectives.get(vocab.normalize(entry.headword))
    if known:
        if known.forms and len(forms) > 1 and [vocab.normalize(f) for f in forms] != [vocab.normalize(f) for f in known.forms]:
            raise Unavailable("The adjective listing differs from morphology.json's dictionary entry.")
        model = replace(known, forms=known.forms or forms)
        if not model.declension:
            return model
        forms = model.forms
    else:
        if len(forms) == 3 and forms[1].endswith("a") and forms[2] == forms[1][:-1] + "um":
            if vocab.normalize(forms[0]) in {"unus", "ullus", "nullus", "solus", "totus", "alter", "uter", "neuter"}:
                raise Unavailable("Set pronominal: true for this adjective in morphology.json.")
            model = Nominal(forms, tuple(GENDERS), 2, quantities_known=False, pos="adjective")
        elif ((len(forms) == 2 and vocab._looks_neuter(forms[1]) and forms[0].endswith("is"))
              or (len(forms) == 3 and forms[1].endswith("is") and forms[2].endswith("e"))):
            model = Nominal(forms, tuple(GENDERS), 3, i_stem=True,
                            quantities_known=False, pos="adjective")
        else:
            raise Unavailable("Specify this adjective's declension and i_stem setting in morphology.json.")
    if model.declension == 2 and len(forms) != 3:
        raise Unavailable("A first/second-declension adjective needs three dictionary forms.")
    if model.declension == 3:
        if len(forms) not in (2, 3):
            raise Unavailable("A third-declension adjective needs two or three dictionary forms.")
        if model.i_stem is None:
            if len(forms) == 3 or vocab._looks_neuter(forms[1]):
                model = replace(model, i_stem=True)
            else:
                raise Unavailable("Specify i_stem: true or false for this one-termination adjective in morphology.json.")
    return model


def verb_model(entry: vocab.Entry, lexicon: Lexicon | None = None) -> Verb:
    lexicon = lexicon or load_lexicon()
    if entry.pos != "verb" or " " in entry.headword:
        raise Unavailable("Needs a single verb rather than a phrase.")
    key = vocab.normalize(entry.headword)
    known = lexicon.verbs.get(lexicon.verb_aliases.get(key, key))
    if known:
        if known.infinitive and len(entry.latin_forms) > 1 and vocab.normalize(entry.latin_forms[1]) != vocab.normalize(known.infinitive):
            raise Unavailable("The listed infinitive differs from the reviewed lexical entry.")
        inf = known.infinitive or (entry.latin_forms[1] if len(entry.latin_forms) > 1 else "")
        if not inf and known.conjugation == "custom":
            inf = known.paradigms["active"]["infinitive"][0]
        if not inf:
            raise Unavailable("Add the verb's infinitive to the chapter or morphology.json.")
        return replace(known, head=known.head or entry.headword, infinitive=inf)
    # A macronized infinitive determines the regular conjugation. Unmarked
    # -ere cannot distinguish 2nd from 3rd and is deliberately not guessed.
    if len(entry.latin_forms) > 1:
        inf = entry.latin_forms[1]
        for ending, conj in (("āre", "1"), ("ēre", "2"), ("īre", "4")):
            if inf.endswith(ending) and vocab.normalize(entry.headword).endswith("o"):
                return Verb(entry.headword, inf, conj, passive=False, quantities_known=False)
    raise Unavailable("Specify this verb's conjugation and passive availability in morphology.json.")


def decline(model: Nominal, gender: str) -> dict[tuple[str, str], list[str]]:
    """Six standard cases; unavailable numbers are absent, not empty answers."""
    adjective = model.pos == "adjective"
    decl = model.declension
    if adjective:
        if decl == 2:
            head = model.forms[tuple(GENDERS).index(gender)]
            stem = model.stem or model.forms[1][:-1]
            decl = 1 if gender == "f" else 2
            gen = stem + ("ae" if decl == 1 else "ī")
        elif decl == 3:
            if len(model.forms) == 3:
                head = model.forms[tuple(GENDERS).index(gender)]
                stem = model.stem or model.forms[1][:-2]
            elif vocab._looks_neuter(model.forms[1]):
                head = model.forms[1] if gender == "n" else model.forms[0]
                stem = model.stem or model.forms[1][:-1]
            else:
                head = model.forms[0]
                stem = model.stem or model.forms[1][:-2]
            gen = stem + "is"
    else:
        if decl:
            head, gen = model.forms
            singular_cut = {1: 2, 2: 1, 3: 2, 4: 2, 5: 2}
            plural_cut = {1: 4, 2: 4, 3: 3 if model.i_stem else 2, 4: 3, 5: 4}
            cut = (plural_cut if model.number == "pl" else singular_cut)[decl]
            stem = model.stem or gen[:-cut]
    neuter = gender == "n"
    if decl == 1:
        sg = [head, gen, stem + "ae", stem + "am", stem + "ā", head]
        pl = [stem + "ae", stem + "ārum", stem + "īs", stem + "ās", stem + "īs", stem + "ae"]
    elif decl == 2:
        voc = head
        if not neuter:
            if not adjective and head.endswith("ius") and (vocab.normalize(head) == "filius" or head[0].isupper()):
                voc = head[:-3] + "ī"
            elif head.endswith("us"):
                voc = head[:-2] + "e"
        sg = [head, gen, stem + "ō", head if neuter else stem + "um", stem + "ō", voc]
        plural_head = stem + ("a" if neuter else "ī")
        pl = [plural_head, stem + "ōrum", stem + "īs",
              plural_head if neuter else stem + "ōs", stem + "īs", plural_head]
    elif decl == 3:
        sg = [head, gen, stem + "ī", head if neuter else stem + "em",
              stem + ("ī" if model.i_stem and (neuter or adjective) else "e"), head]
        plural_head = stem + ("ia" if model.i_stem else "a") if neuter else stem + "ēs"
        pl = [plural_head, stem + ("ium" if model.i_stem else "um"), stem + "ibus",
              plural_head, stem + "ibus", plural_head]
    elif decl == 4:
        sg = [head, gen, stem + ("ū" if neuter else "uī"), head if neuter else stem + "um", stem + "ū", head]
        plural_head = stem + ("ua" if neuter else "ūs")
        pl = [plural_head, stem + "uum", stem + "ibus", plural_head, stem + "ibus", plural_head]
    elif decl == 5:
        sg = [head, gen, gen, stem + "em", stem + "ē", head]
        pl = [stem + "ēs", stem + "ērum", stem + "ēbus", stem + "ēs", stem + "ēbus", stem + "ēs"]
    out = {(case, number): [forms[i]] for number, forms in zip(NUMBERS, (sg, pl))
           for i, case in enumerate(CASES)} if decl else {}
    if decl == 2 and not adjective and model.number != "pl" and stem.endswith("i"):
        out["genitive", "singular"].append(stem[:-1] + "ī")
    if decl == 3 and model.i_stem and not neuter:
        out["accusative", "plural"].append(stem + "īs")
    if decl == 4 and not neuter:
        out["dative", "singular"].append(stem + "ū")
    if adjective and model.pronominal:
        out["genitive", "singular"] = [stem + "īus"]
        out["dative", "singular"] = [stem + "ī"]
    overrides = model.overrides.get(gender, {}) if adjective else model.overrides
    for key, answers in overrides.items():
        case, number = key.rsplit("_", 1)
        if answers is None:
            out.pop((case, number), None)
        else:
            out[case, number] = list(answers)
    return {key: value for key, value in out.items()
            if model.number is None or key[1] == ("plural" if model.number == "pl" else "singular")}


def conjugate(model: Verb, voice: str) -> tuple[list[list[str]], list[str]]:
    if voice not in ("active", "passive") or (voice == "passive" and not model.passive):
        raise Unavailable("This verb does not have a supported six-person passive paradigm.")
    keys = [f"p{p}_{number}" for number in NUMBERS for p in range(1, 4)]
    if voice in model.paradigms:
        table = {key: list(answers) for key, answers in model.paradigms[voice].items()}
    else:
        root = model.stem or model.infinitive[:-3]
        active = {"1": "ō ās at āmus ātis ant", "2": "eō ēs et ēmus ētis ent",
                  "3": "ō is it imus itis unt", "3io": "iō is it imus itis iunt",
                  "4": "iō īs it īmus ītis iunt"}
        passive = {"1": "or āris ātur āmur āminī antur", "2": "eor ēris ētur ēmur ēminī entur",
                   "3": "or eris itur imur iminī untur", "3io": "ior eris itur imur iminī iuntur",
                   "4": "ior īris ītur īmur īminī iuntur"}
        endings = (active if voice == "active" else passive)[model.conjugation].split()
        active_infinitives = {"1": "āre", "2": "ēre", "3": "ere", "3io": "ere", "4": "īre"}
        passive_infinitives = {"1": "ārī", "2": "ērī", "3": "ī", "3io": "ī", "4": "īrī"}
        inf = root + (active_infinitives if voice == "active" else passive_infinitives)[model.conjugation]
        forms = [[root + ending] for ending in endings]
        if voice == "passive":
            forms[1].append(forms[1][0][:-3] + "re")
        table = dict(zip(keys, forms))
        table["infinitive"] = [inf]
    table.update({key: list(answers) for key, answers in model.overrides.get(voice, {}).items()})
    return [table[key] for key in keys], table["infinitive"]


def options(req: dict) -> dict:
    kinds = req.get("kinds", list(KINDS))
    if not isinstance(kinds, list) or not kinds or any(k not in KINDS for k in kinds):
        raise ValueError("Select at least one valid entry type.")
    voice, gender = req.get("voice", "mixed"), req.get("gender", "mixed")
    if voice not in ("active", "passive", "mixed") or gender not in (*GENDERS, "mixed"):
        raise ValueError("Select a valid verb voice and adjective gender.")
    count = max(1, min(int(req.get("count") or 10), 500))
    return {"kinds": list(dict.fromkeys(kinds)), "voice": voice, "gender": gender,
            "count": count, "exhaustive": bool(req.get("exhaustive")),
            "shuffle": bool(req.get("shuffle", True))}


def candidates(pool: list[vocab.Entry], opts: dict,
               rng: random.Random | None = None,
               lexicon: Lexicon | None = None) -> tuple[list[dict], list[dict], dict]:
    rng = rng or random.Random()
    lexicon = lexicon or load_lexicon()
    groups: dict[str, list[tuple]] = {k: [] for k in KINDS[:3]}
    excluded = []
    wanted = set(opts["kinds"])
    relevant = wanted | ({"noun", "adjective"} if "pair" in wanted else set())
    for entry in pool:
        if entry.pos not in relevant:
            continue
        try:
            model = {"noun": noun_model, "adjective": adjective_model, "verb": verb_model}[entry.pos](entry, lexicon)
            if entry.pos == "verb" and opts["voice"] == "passive" and not model.passive:
                raise Unavailable("No supported six-person personal passive for this chapter sense.")
            groups[entry.pos].append((entry, model))
        except Unavailable as exc:
            excluded.append({"word": entry.headword, "source": entry.source, "reason": str(exc)})
    available = []
    for kind in KINDS[:3]:
        if kind in wanted:
            available.extend({"kind": kind, "entry": e, "model": m} for e, m in groups[kind])
    if "pair" in wanted and groups["noun"] and groups["adjective"]:
        nouns, adjectives = list(groups["noun"]), list(groups["adjective"])
        if opts["shuffle"]:
            rng.shuffle(nouns)
            rng.shuffle(adjectives)
        # Exhaustive pairs cover every eligible noun AND adjective at least
        # once, cycling the shorter list; never form a Cartesian product.
        for i in range(max(len(nouns), len(adjectives))):
            (noun, nm), (adj, am) = nouns[i % len(nouns)], adjectives[i % len(adjectives)]
            available.append({"kind": "pair", "entry": noun, "model": nm,
                              "adjective": adj, "adjective_model": am})
    counts = {kind: sum(c["kind"] == kind for c in available) for kind in KINDS}
    return available, excluded, counts


def _cell(key: str, label: str, answers: list[str] | None, quantities_known: bool) -> dict:
    accepted, strict = vocab.variant_sets(answers or [])
    return {"key": key, "label": label, "answer": " / ".join(answers or []),
            "accepted": accepted, "strict": strict, "disabled": answers is None,
            "quantities_known": quantities_known}


def question(candidate: dict, index: int, opts: dict, rng: random.Random) -> dict:
    kind, entry, model = candidate["kind"], candidate["entry"], candidate["model"]
    q = {"index": index, "kind": kind, "source": entry.source,
         "prompt": entry.headword, "meaning": entry.english_core,
         "full_entry": f"{entry.raw_latin} – {entry.english}", "fields": [],
         "rows": [], "columns": [], "notes": [], "entry_key": entry.key}
    identity = [kind, entry.key]
    if kind == "verb":
        voice = (rng.choice(["active", "passive"]) if model.passive else "active") if opts["voice"] == "mixed" else opts["voice"]
        forms, inf = conjugate(model, voice)
        q.update(prompt=model.head, prompt_label=f"Present {voice} indicative", voice=voice,
                 columns=["Singular", "Plural"], rows=["1st person", "2nd person", "3rd person"])
        for number_i, number in enumerate(NUMBERS):
            for person in range(3):
                q["fields"].append(_cell(f"p{person + 1}_{number}", f"{person + 1}{'st' if person == 0 else 'nd' if person == 1 else 'rd'} person {number}",
                                         forms[number_i * 3 + person], model.quantities_known))
        q["fields"].append(_cell("infinitive", f"Present {voice} infinitive", inf, model.quantities_known))
        identity.append(voice)
    else:
        gender = (rng.choice(list(GENDERS)) if opts["gender"] == "mixed" else opts["gender"]) if kind == "adjective" else rng.choice(model.genders)
        forms = decline(model, gender)
        known_quantities = model.quantities_known
        q.update(gender=gender, columns=["Singular", "Plural"], rows=[c.title() for c in CASES])
        if kind == "pair":
            adj, am = candidate["adjective"], candidate["adjective_model"]
            af = decline(am, gender)
            forms = {cell: list(dict.fromkeys(
                phrase for n, a in product(answers, af[cell]) for phrase in (f"{n} {a}", f"{a} {n}")))
                for cell, answers in forms.items() if cell in af}
            # Display canonical noun-first answers, but accept either order.
            q.update(prompt=f"{model.forms[0]} + {am.forms[0]}",
                     meaning=f"{entry.english_core} + {adj.english_core}",
                     source=" + ".join(dict.fromkeys([entry.source, adj.source])),
                     full_entry=q["full_entry"] + f"; {adj.raw_latin} – {adj.english}")
            q["notes"].append("Write the noun and adjective together in each cell; either word order is accepted.")
            identity.append(adj.key)
            known_quantities = known_quantities and am.quantities_known
        elif kind == "adjective":
            q["prompt"] = ", ".join(model.forms)
        else:
            q["prompt"] = ", ".join(model.forms)
        q["prompt_label"] = f"Decline {'the noun and agreeing adjective' if kind == 'pair' else 'the ' + kind} · {GENDERS[gender]}"
        restriction = model.number or (am.number if kind == "pair" else None)
        if restriction:
            q["notes"].append("Plural only." if restriction == "pl" else "Singular only.")
        for case in CASES:
            for number in NUMBERS:
                cell = _cell(f"{case}_{number}", f"{case.title()} {number}", forms.get((case, number)), known_quantities)
                if kind == "pair" and not cell["disabled"]:
                    cell["answer"] = " / ".join(forms[case, number][::2])
                q["fields"].append(cell)
        identity.append(gender)
    q["identity"] = "|".join(identity)
    return q


def build_quiz(pool: list[vocab.Entry], opts: dict, rng: random.Random | None = None,
               lexicon: Lexicon | None = None) -> dict:
    rng = rng or random.Random()
    available, excluded, counts = candidates(pool, opts, rng, lexicon)
    chosen = vocab.select_entries(available, opts["count"], opts["exhaustive"], opts["shuffle"], rng)
    if not opts["shuffle"]:
        order = {id(c): i for i, c in enumerate(available)}
        chosen.sort(key=lambda c: order[id(c)])
    return {"questions": [question(c, i, opts, rng) for i, c in enumerate(chosen)],
            "pool": len(available), "counts": counts, "excluded": excluded,
            "exhaustive": opts["exhaustive"]}


def public(questions: list[dict]) -> list[dict]:
    keys = ("index", "kind", "source", "prompt", "prompt_label", "meaning", "rows", "columns", "notes")
    return [{**{k: q[k] for k in keys},
             "fields": [{k: f[k] for k in ("key", "label", "disabled")} for f in q["fields"]]}
            for q in questions]


def grade(questions: list[dict], answers: list[dict]) -> dict:
    results, missed = [], {}
    entry_correct = field_correct = field_total = 0
    for q in questions:
        given = answers[q["index"]] if q["index"] < len(answers) else {}
        supplied = given.get("fields", {})
        fields = []
        for f in q["fields"]:
            value = str(supplied.get(f["key"]) or "").strip()
            if f["disabled"]:
                verdict = "unavailable"
            else:
                verdict = vocab.check(value, set(f["accepted"]), set(f["strict"]))
                if verdict == "macrons" and not f["quantities_known"]:
                    verdict = "correct"
                field_total += 1
                field_correct += verdict != "wrong"
            fields.append({"key": f["key"], "label": f["label"], "disabled": f["disabled"],
                           "given": value, "answer": f["answer"], "verdict": verdict})
        wrong = any(f["verdict"] == "wrong" for f in fields)
        entry_correct += not wrong
        if wrong:
            missed.setdefault(q["identity"], q["index"])
        results.append({**public([q])[0], "fields": fields, "full_entry": q["full_entry"],
                        "verdict": "wrong" if wrong else "macrons" if any(f["verdict"] == "macrons" for f in fields) else "correct"})
    return {"results": results,
            "score": {"entry_correct": entry_correct, "entry_total": len(questions),
                      "field_correct": field_correct, "field_total": field_total,
                      "missed": len(missed)}, "missed": list(missed.values())}


def retest(questions: list[dict], missed: list[int], rng: random.Random | None = None) -> list[dict]:
    chosen = [deepcopy(questions[i]) for i in missed]
    (rng or random.Random()).shuffle(chosen)
    for i, q in enumerate(chosen):
        q["index"] = i
    return chosen
