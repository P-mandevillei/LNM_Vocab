"""Offline morphology quizzes with chapter, rule and imported answer schemes.

Bundled and user-defined lexical data supply quantities and exceptions which
cannot be recovered from unmacronized chapter notes. Regular inflection rules
follow Allen & Greenough (see README.md). Ready imported tables provide a
second answer scheme and additional grammatical topics. No network is used
to draw or grade a quiz. Missing forms are disabled, never guessed.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from itertools import product
import random

import vocab
import morphology_answers as answers
from morphology_cache import table_sources, lookup
from morphology_data import (CASES, NUMBERS, GENDERS, Lexicon, Nominal, Verb,
                             load_lexicon)

KINDS = ("noun", "adjective", "verb", "pair")
VOICES = ("active", "passive")
TENSES = ("present", "imperfect", "future", "perfect", "pluperfect", "future_perfect")
MOODS = ("indicative", "subjunctive", "imperative")


class Unavailable(ValueError):
    """An entry does not have enough verified information for an answer key."""


# Compatibility names for the bundled data; new quizzes load vault overrides.
_DEFAULT_LEXICON = load_lexicon(include_custom=False, include_cache=False)
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
    selections = {}
    for name, valid, default in (("voices", VOICES, list(VOICES) if voice == "mixed" else [voice]),
                                  ("tenses", TENSES, ["present"]),
                                  ("moods", MOODS, ["indicative"])):
        values = req.get(name, default)
        if not isinstance(values, list) or any(v not in valid for v in values) or ("verb" in kinds and not values):
            raise ValueError(f"Select at least one valid verb {name} choice.")
        selections[name] = list(dict.fromkeys(values))
    return {"kinds": list(dict.fromkeys(kinds)), "voice": voice, "gender": gender, **selections,
            "count": count, "exhaustive": bool(req.get("exhaustive")),
            "shuffle": bool(req.get("shuffle", True))}


def candidates(pool: list[vocab.Entry], opts: dict,
               rng: random.Random | None = None,
               lexicon: Lexicon | None = None, sources=None) -> tuple[list[dict], list[dict], dict]:
    rng = rng or random.Random()
    lexicon = lexicon or load_lexicon(include_cache=False)
    sources = sources if sources is not None else table_sources()
    groups: dict[str, list[tuple]] = {k: [] for k in KINDS[:3]}
    excluded = []
    wanted = set(opts["kinds"])
    relevant = wanted | ({"noun", "adjective"} if "pair" in wanted else set())
    for entry in pool:
        if entry.pos not in relevant:
            continue
        try:
            try:
                model = {"noun": noun_model, "adjective": adjective_model, "verb": verb_model}[entry.pos](entry, lexicon)
            except Unavailable:
                record = sources.record_for(entry)
                if not record or (entry.pos == "noun" and not record["request"].get("genders")):
                    raise
                req = record["request"]
                if entry.pos == "verb":
                    head = vocab.normalize(entry.headword)
                    reviewed = lexicon.verbs.get(lexicon.verb_aliases.get(head, head))
                    # Preserve explicit restrictions for known chapter senses.
                    # The importer's default False for an unclassified word
                    # is not evidence that its cached passive is impossible.
                    passive = reviewed.passive if reviewed else any(
                        c["features"].get("voice") == "passive" and c["features"].get("mood") and c["forms"]
                        for c in record["candidate"]["cells"].values())
                    model = Verb(req["forms"][0], req["forms"][1] if len(req["forms"]) > 1 else "",
                                 "cached", passive=bool(passive), quantities_known=False)
                else:
                    model = Nominal(tuple(req["forms"]), tuple(req.get("genders") or GENDERS), 0,
                                    number=req.get("number"), quantities_known=False, pos=entry.pos)
            record = sources.record_for(entry, model)
            configurations = verb_configurations(model, record, opts) if entry.pos == "verb" else []
            if entry.pos == "verb" and not configurations:
                raise Unavailable("No complete cached or rule-based table matches the selected voice, tense and mood (or the chapter's passive restriction).")
            groups[entry.pos].append((entry, model, record, configurations))
        except Unavailable as exc:
            excluded.append({"word": entry.headword, "source": entry.source, "reason": str(exc)})
    available = []
    for kind in KINDS[:3]:
        if kind in wanted:
            available.extend({"kind": kind, "entry": e, "model": m, "record": record,
                              "configurations": configurations} for e, m, record, configurations in groups[kind])
    if "pair" in wanted and groups["noun"] and groups["adjective"]:
        nouns, adjectives = list(groups["noun"]), list(groups["adjective"])
        if opts["shuffle"]:
            rng.shuffle(nouns)
            rng.shuffle(adjectives)
        # Exhaustive pairs cover every eligible noun AND adjective at least
        # once, cycling the shorter list; never form a Cartesian product.
        for i in range(max(len(nouns), len(adjectives))):
            (noun, nm, nr, _), (adj, am, ar, _) = nouns[i % len(nouns)], adjectives[i % len(adjectives)]
            available.append({"kind": "pair", "entry": noun, "model": nm,
                              "record": nr, "adjective": adj, "adjective_model": am,
                              "adjective_record": ar})
    counts = {kind: sum(c["kind"] == kind for c in available) for kind in KINDS}
    return available, excluded, counts


def rule_conjugation(model, voice, tense, mood):
    if tense == "present" and mood == "indicative" and model.conjugation != "cached":
        forms, infinitive = conjugate(model, voice)
        return {f"p{person}_{number}": forms[i * 3 + person - 1]
                for i, number in enumerate(NUMBERS) for person in range(1, 4)}, infinitive
    return {}, []


def verb_configurations(model, record, opts):
    configurations = []
    for voice, tense, mood in product(opts["voices"], opts["tenses"], opts["moods"]):
        if voice == "passive" and not model.passive:
            continue
        rules, _ = rule_conjugation(model, voice, tense, mood)
        cells = [lookup(record["candidate"], pos="verb", voice=voice, tense=tense,
                        mood=mood, person=person, number=number) if record else None
                 for number in NUMBERS for person in range(1, 4)]
        if rules or (any(c and c["forms"] for c in cells) and
                     (mood == "imperative" or all(c is not None for c in cells))):
            configurations.append((voice, tense, mood))
    return configurations


def nominal_cell(entry, model, record, gender, case, number, rules):
    restricted = model.number and number != ("plural" if model.number == "pl" else "singular")
    features = {"pos": entry.pos, "case": case, "number": number}
    if entry.pos == "adjective":
        features.update(gender=gender, degree="positive")
    return answers.cell(f"{case}_{number}", f"{case.title()} {number}",
                        answers.chapter_nominal(entry, model, gender, case, number),
                        rules.get((case, number), []), answers.imported(record, **features),
                        model.quantities_known, disabled=bool(restricted))


def question(candidate: dict, index: int, opts: dict, rng: random.Random) -> dict:
    kind, entry, model = candidate["kind"], candidate["entry"], candidate["model"]
    record = candidate.get("record")
    q = {"index": index, "kind": kind, "source": entry.source,
         "prompt": model.head if kind == "verb" else model.forms[0],
         "full_entry": f"{entry.raw_latin} – {entry.english}", "fields": [],
         "rows": [], "columns": [], "notes": [], "entry_key": entry.key}
    identity = [kind, entry.key]
    if kind == "verb":
        voice, tense, mood = rng.choice(candidate["configurations"])
        rules, rule_inf = rule_conjugation(model, voice, tense, mood)
        q.update(prompt_label=f"{tense.replace('_', ' ').title()} {voice} {mood}", voice=voice, tense=tense, mood=mood,
                 columns=["Singular", "Plural"], rows=["1st person", "2nd person", "3rd person"])
        for number in NUMBERS:
            for person in range(1, 4):
                key = f"p{person}_{number}"
                features = dict(voice=voice, tense=tense, mood=mood, person=person, number=number)
                q["fields"].append(answers.cell(key, f"{person}{('st', 'nd', 'rd')[person - 1]} person {number}",
                    answers.chapter_verb(entry, model, **features), rules.get(key, []),
                    answers.imported(record, pos="verb", **features), model.quantities_known))
        inf_tense = "perfect" if tense in ("perfect", "pluperfect", "future_perfect") else "present"
        # The v1 rules supply present infinitives regardless of finite mood.
        if inf_tense == "present" and model.conjugation != "cached":
            _, rule_inf = conjugate(model, voice)
        features = dict(voice=voice, tense=inf_tense, form="infinitive")
        q["fields"].append(answers.cell("infinitive", f"{inf_tense.title()} {voice} infinitive",
            answers.chapter_verb(entry, model, **features), rule_inf,
            answers.imported(record, pos="verb", **features), model.quantities_known))
        identity.extend((voice, tense, mood))
    else:
        gender = (rng.choice(list(GENDERS)) if opts["gender"] == "mixed" else opts["gender"]) if kind == "adjective" else rng.choice(model.genders)
        forms = decline(model, gender)
        q.update(gender=gender, columns=["Singular", "Plural"], rows=[c.title() for c in CASES])
        if kind == "pair":
            adj, am = candidate["adjective"], candidate["adjective_model"]
            af = decline(am, gender)
            q.update(prompt=f"{model.forms[0]} + {am.forms[0]}",
                     source=" + ".join(dict.fromkeys([entry.source, adj.source])),
                     full_entry=q["full_entry"] + f"; {adj.raw_latin} – {adj.english}")
            q["notes"].append("Write the noun and adjective together in each cell; either word order is accepted.")
            identity.append(adj.key)
        q["prompt_label"] = f"Decline {'the noun and agreeing adjective' if kind == 'pair' else 'the ' + kind} · {GENDERS[gender]}"
        restriction = model.number or (am.number if kind == "pair" else None)
        if restriction:
            q["notes"].append("Plural only." if restriction == "pl" else "Singular only.")
        for case in CASES:
            for number in NUMBERS:
                cell = nominal_cell(entry, model, record, gender, case, number, forms)
                if kind == "pair":
                    ac = nominal_cell(adj, am, candidate.get("adjective_record"), gender, case, number, af)
                    cell = answers.pair_cell(cell["key"], cell["label"], cell, ac)
                q["fields"].append(cell)
        identity.append(gender)
    q["identity"] = "|".join(identity)
    return q


def build_quiz(pool: list[vocab.Entry], opts: dict, rng: random.Random | None = None,
               lexicon: Lexicon | None = None, sources=None) -> dict:
    rng = rng or random.Random()
    available, excluded, counts = candidates(pool, opts, rng, lexicon, sources)
    chosen = vocab.select_entries(available, opts["count"], opts["exhaustive"], opts["shuffle"], rng)
    if not opts["shuffle"]:
        order = {id(c): i for i, c in enumerate(available)}
        chosen.sort(key=lambda c: order[id(c)])
    return {"questions": [question(c, i, opts, rng) for i, c in enumerate(chosen)],
            "pool": len(available), "counts": counts, "excluded": excluded,
            "exhaustive": opts["exhaustive"]}


def public(questions: list[dict]) -> list[dict]:
    keys = ("index", "kind", "source", "prompt", "prompt_label", "rows", "columns", "notes")
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
                           "given": value, "answer": f["answer"], "verdict": verdict,
                           **{key: f.get(key, default) for key, default in
                              (("answer_sources", {}), ("disagreement", False), ("chapter_precedence", False))}})
        wrong = any(f["verdict"] == "wrong" for f in fields)
        entry_correct += not wrong
        if wrong:
            missed.setdefault(q["identity"], q["index"])
        results.append({**public([q])[0], "fields": fields, "full_entry": q["full_entry"],
                        "unfamiliar": bool(given.get("unfamiliar", False)),
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
