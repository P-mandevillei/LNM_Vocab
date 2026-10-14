"""Offline, per-cell chapter precedence and independent answer schemes."""

from itertools import product

import vocab
from morphology_cache import lookup


def imported(record, **features):
    if not record:
        return []
    cell = lookup(record["candidate"], **features)
    return list(cell["forms"]) if cell else []


def chapter_nominal(entry, model, gender, case, number):
    """Dictionary slots are evidence only for the cells they explicitly name."""
    forms = entry.latin_forms
    listed_number = "plural" if (entry.number or model.number) == "pl" else "singular"
    if number != listed_number or not forms:
        return []
    if entry.pos == "noun":
        index = {"nominative": 0, "genitive": 1}.get(case)
    elif len(forms) == 3:
        index = "mfn".index(gender) if case == "nominative" else None
    elif len(forms) == 2 and vocab._looks_neuter(forms[1]):
        index = (1 if gender == "n" else 0) if case == "nominative" else None
    else:  # One termination: nominative, genitive.
        index = {"nominative": 0, "genitive": 1}.get(case)
    return [forms[index]] if index is not None and index < len(forms) else []


def chapter_verb(entry, model, *, voice, tense, mood=None, person=None, number=None, form=None):
    if voice != "active":
        return []
    # Entry.latin_forms drops placeholders; retain original principal-part
    # positions so a supplied fourth part cannot masquerade as a perfect.
    parts = [part.strip() for part in entry.raw_latin.split(",")] if entry.raw_latin else entry.latin_forms
    parts = ["" if vocab.PLACEHOLDER_RE.fullmatch(part) else part for part in parts]
    if form == "infinitive":
        return [parts[1]] if tense == "present" and len(parts) > 1 else []
    if mood != "indicative" or number != "singular":
        return []
    if tense == "perfect" and person == 1 and len(parts) > 2 and parts[2]:
        return [parts[2]]
    if tense == "present":
        # Early chapters list amat/est, whereas most list the 1st person.
        head_person = 1 if vocab.normalize(parts[0]) == vocab.normalize(model.head) else 3
        return [parts[0]] if person == head_person else []
    return []


def cell(key, label, chapter=(), rule=(), importer=(), quantities_known=True, disabled=False):
    sources = {name: list(forms) for name, forms in
               (("chapter", chapter), ("rule", rule), ("importer", importer)) if forms}
    answers = list(chapter)
    if not chapter:
        seen = set()
        for value in [*rule, *importer]:
            spelling = vocab.normalize(value)
            if spelling not in seen:
                answers.append(value)
                seen.add(spelling)
    accepted, strict = vocab.variant_sets(answers)
    # Quantity annotations in the provider are not reliable spelling keys.
    # Compare spelling variant sets, consistent with optional-macron grading.
    disagreement = bool(rule and importer and
                        set(vocab.variant_sets(rule)[0]) != set(vocab.variant_sets(importer)[0]))
    return {"key": key, "label": label, "answer": " / ".join(answers),
            "accepted": accepted, "strict": strict,
            "disabled": disabled or not answers,
            "quantities_known": bool(chapter) or (quantities_known and not importer),
            "answer_sources": sources, "disagreement": disagreement,
            "chapter_precedence": bool(chapter)}


def pair_cell(key, label, noun, adjective):
    def phrases(left, right, both_orders=True):
        return list(dict.fromkeys(phrase for n, a in product(left, right)
                    for phrase in ((f"{n} {a}", f"{a} {n}") if both_orders else (f"{n} {a}",))))
    # Each component obeys its own chapter precedence. Cross-scheme pairs
    # are valid when each component is independently valid.
    left = noun["answer"].split(" / ") if noun["answer"] else []
    right = adjective["answer"].split(" / ") if adjective["answer"] else []
    result = cell(key, label, rule=phrases(left, right),
                  quantities_known=noun["quantities_known"] and adjective["quantities_known"],
                  disabled=noun["disabled"] or adjective["disabled"])
    result["answer"] = " / ".join(phrases(left, right, False))
    result["answer_sources"] = {f"{part} {name}": forms
        for part, component in (("noun", noun), ("adjective", adjective))
        for name, forms in component["answer_sources"].items()}
    result["disagreement"] = noun["disagreement"] or adjective["disagreement"]
    result["chapter_precedence"] = noun["chapter_precedence"] or adjective["chapter_precedence"]
    return result
