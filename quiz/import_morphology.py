"""Incrementally acquire Collatinus tables before deployment, never at runtime.

Run --dry-run first. --compare audits imported forms against the retained local
schema without treating that schema as the source of the imported answers.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError

import collatinus as provider
import morphology as m
from morphology_cache import DEFAULT_CACHE, CacheError, cache_lock, load_cache, lookup, save_json
import vocab


HERE = Path(__file__).resolve().parent
INFLECTABLE = {"noun", "adjective", "verb", "pronoun", "numeral", "participle"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def inventory(vault):
    lexicon = m.load_lexicon(vault, include_cache=False)
    requests, bindings, skipped, references = {}, {}, {}, {}
    for entries in vocab.load_vault(vault).values():
        for entry in entries:
            raw = {"pos": entry.pos, "forms": entry.latin_forms, "gender": entry.gender, "number": entry.number}
            binding_id = digest(raw)
            if entry.pos not in INFLECTABLE or " " in entry.headword:
                skipped[binding_id] = {"word": entry.headword, "pos": entry.pos,
                    "reason": "Not an inflectable word" if entry.pos not in INFLECTABLE else "Phrase requires an explicit lemma mapping"}
                continue
            model = None
            try:
                if entry.pos in ("noun", "adjective", "verb"):
                    model = {"noun": m.noun_model, "adjective": m.adjective_model, "verb": m.verb_model}[entry.pos](entry, lexicon)
            except m.Unavailable:
                pass
            if entry.pos == "verb" and model:
                forms = [model.head, model.infinitive]
            elif model:
                forms = list(model.forms)
            else:
                forms = list(entry.latin_forms)
            principal_parts = [*forms[:2], *entry.latin_forms[2:]] if entry.pos == "verb" else None
            if entry.pos == "verb":
                forms = forms[:2]
            # Full principal parts remain on each binding; canonical dictionary
            # identity allows early chapter aliases to share the same request.
            identity = {"pos": entry.pos, "forms": forms}
            key = digest(identity)
            request = {**identity, "query": forms[0], "number": getattr(model, "number", entry.number),
                       "genders": list(getattr(model, "genders", ())),
                       "passive": getattr(model, "passive", False)}
            if not request["genders"] and entry.gender:
                parsed = vocab._split_gender(entry.gender)
                request["genders"] = [g for g in parsed[0] if g in ("m", "f", "n")] if parsed else []
            requests.setdefault(key, request)
            if principal_parts and len(principal_parts) > len(requests[key].get("principal_parts", [])):
                requests[key]["principal_parts"] = principal_parts
            bindings[binding_id] = {"entry": key, "input": raw}
            if model:
                references.setdefault(key, model)
    return requests, bindings, skipped, references


def resolve(candidates, request):
    pos = request["pos"]
    eligible = [c for c in candidates if pos in c["kinds"]]
    words = [provider.dictionary_spelling(f) for f in request["forms"]]
    matched = []
    def contains(candidate, word, **features):
        cell = lookup(candidate, pos=pos, **features)
        return bool(cell and word in {provider.dictionary_spelling(f) for f in cell["forms"]})
    for candidate in eligible:
        head_matches = words[0] in {provider.dictionary_spelling(head) for head in candidate["headword"].split(",")}
        compatible = False
        if pos == "verb":
            compatible = head_matches and (len(words) == 1 or any(contains(candidate, words[1],
                form="infinitive", tense="present", voice=voice) for voice in ("active", "passive")))
        elif pos == "noun" and len(words) >= 2:
            numbers = ["plural"] if request.get("number") == "pl" else ["singular"] if request.get("number") == "sg" else ["singular", "plural"]
            compatible = any(contains(candidate, words[0], case="nominative", number=num) and
                             contains(candidate, words[1], case="genitive", number=num) for num in numbers)
        elif pos == "adjective":
            num = "plural" if request.get("number") == "pl" else "singular"
            if len(words) == 3:
                compatible = all(contains(candidate, word, case="nominative", number=num, gender=g, degree="positive")
                                 for g, word in zip(("m", "f", "n"), words))
            elif len(words) == 2:
                compatible = any(contains(candidate, words[0], case="nominative", number=num, gender=g, degree="positive")
                                 for g in ("m", "f")) and (contains(candidate, words[1], case="nominative", number=num,
                                    gender="n", degree="positive") or contains(candidate, words[1], case="genitive",
                                    number=num, gender="m", degree="positive"))
        else:
            compatible = head_matches
        if compatible:
            matched.append(candidate)
    if not matched and len(words) == 1 and len(eligible) == 1:
        matched = eligible
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        signatures = {digest({k: {"forms": sorted(c["forms"]),
                                  "quantified": sorted(provider.quantified(f) for f in c["source_forms"])}
                              for k, c in candidate["cells"].items()
                              if c["features"]["pos"] == pos and (not request.get("number") or
                                  c["features"].get("number") == ("plural" if request["number"] == "pl" else "singular"))})
                      for candidate in matched}
        if len(signatures) == 1:
            chosen = deepcopy(sorted(matched, key=lambda c: c["id"])[0])
            chosen["equivalent_lemma_ids"] = sorted(c["id"] for c in matched)
            return chosen
    return None


def import_tables(vault, cache_path=DEFAULT_CACHE, *, client=None, dry_run=False, offline=False,
                  retry_errors=False, retry_missing=False, refresh=(), limit=None, reparse=False,
                  progress=print):
    cache_path = Path(cache_path)
    data = load_cache(cache_path)
    requests, bindings, skipped, _ = inventory(vault)
    stats = Counter(requested=len(requests), reused=0, acquired=0, calls=0, errors=0,
                    ambiguous=0, not_found=0, pending=0)
    refresh = set(refresh)
    raw_dir = cache_path.parent / "collatinus_raw"
    if not dry_run:
        data["skipped"].update(skipped)
    count = 0
    for index, (key, request) in enumerate(sorted(requests.items(), key=lambda item: (item[1]["pos"], item[1]["query"]))):
        previous = data["entries"].get(key)
        forced = key in refresh or vocab.normalize(request["query"]) in {vocab.normalize(w) for w in refresh}
        needs_retry = previous and ((retry_errors and previous["status"] == "error") or
                                    (retry_missing and previous["status"] in ("not_found", "ambiguous")))
        due = previous and previous.get("retry_after") and previous["retry_after"] <= now()
        fetch = not previous or forced or needs_retry or (previous["status"] == "error" and due)
        parse_raw = reparse and previous and previous.get("raw_file") and (not refresh or forced)
        if previous and not fetch and not parse_raw:
            stats["reused"] += 1
            if not dry_run:
                if data["entries"][key]["request"] != request:
                    data["entries"][key]["review_status"] = "unreviewed"
                data["entries"][key]["request"] = request
            continue
        if limit is not None and count >= limit:
            stats["pending"] += 1
            continue
        if dry_run or (offline and not parse_raw):
            stats["pending"] += 1
            progress(f"Would acquire: {request['pos']} {request['query']}")
            continue
        count += 1
        record = {"request": request, "status": "error", "review_status": "unreviewed",
                  "provider": provider.PROVIDER, "endpoint": getattr(client, "endpoint", provider.ENDPOINT),
                  "source": provider.SOURCE, "parser_version": provider.PARSER_VERSION, "last_attempt": now()}
        try:
            if parse_raw:
                saved_path = (cache_path.parent / previous["raw_file"]).resolve()
                if not saved_path.is_relative_to(raw_dir.resolve()):
                    raise CacheError("Raw response path is outside the cache's source directory")
                content = saved_path.read_bytes()
            else:
                client = client or provider.CollatinusClient()
                stats["calls"] += 1
                content = client.fetch(provider.unmarked(request["query"]))
            content_hash = hashlib.sha256(content).hexdigest()
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"{content_hash}.html"
            if not raw_path.exists():
                raw_path.write_bytes(content)
            record.update(raw_file=raw_path.relative_to(cache_path.parent).as_posix(), response_sha256=content_hash,
                          fetched_at=previous.get("fetched_at", now()) if parse_raw else now())
            candidates = provider.parse_response(content)
            candidate = resolve(candidates, request)
            if not candidates:
                record.update(status="not_found", reason="Provider returned no lemmas")
                stats["not_found"] += 1
            elif candidate is None:
                record.update(status="ambiguous", reason="No unique compatible dictionary entry",
                              candidates=[{k: c[k] for k in ("id", "headword", "description", "kinds")} for c in candidates])
                stats["ambiguous"] += 1
            else:
                coverage = sorted({provider.feature_key({k: v for k, v in cell["features"].items()
                                    if k not in ("case", "number", "person")})
                                   for cell in candidate["cells"].values()})
                record.update(status="ready", candidate=candidate, quantities_known=False,
                              coverage=coverage, review_status="unreviewed")
                # Re-parsing the same source does not silently grant approval.
                if (previous and previous.get("response_sha256") == content_hash and
                        previous.get("candidate") == candidate and previous.get("request") == request):
                    record["review_status"] = previous.get("review_status", "unreviewed")
                stats["acquired"] += 1
        except (ValueError, OSError, URLError) as exc:
            record.update(reason=f"{type(exc).__name__}: {exc}",
                          retry_after=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds"))
            stats["errors"] += 1
        if previous and previous["status"] == "ready" and record["status"] != "ready":
            retained = deepcopy(previous)
            retained["last_refresh_error"] = {"at": now(), "reason": record.get("reason", "Unusable response"),
                                               "status": record["status"]}
            record = retained
        elif (previous and previous.get("review_status") == "approved" and
              record["status"] == "ready" and record.get("review_status") != "approved"):
            retained = deepcopy(previous)
            retained["pending_refresh"] = record
            record = retained
        data["entries"][key] = record
        # Only attach bindings whose requests have a saved acquisition record.
        data["bindings"].update({k: b for k, b in bindings.items() if b["entry"] in data["entries"]})
        save_json(cache_path, data)
        progress(f"{index + 1}/{len(requests)} {request['pos']} {request['query']}: {record['status']}")
    if not dry_run:
        data["bindings"].update({k: b for k, b in bindings.items() if b["entry"] in data["entries"]})
        save_json(cache_path, data)
    return dict(stats)


def reference_cells(request, model):
    if request["pos"] in ("noun", "adjective"):
        for gender in model.genders:
            for (case, number), forms in m.decline(model, gender).items():
                features = {"pos": request["pos"], "case": case, "number": number}
                if request["pos"] == "adjective":
                    features.update(gender=gender, degree="positive")
                yield features, forms, gender
    elif request["pos"] == "verb":
        for voice in (("active", "passive") if model.passive else ("active",)):
            forms, inf = m.conjugate(model, voice)
            for index, answers in enumerate(forms):
                yield {"pos": "verb", "mood": "indicative", "tense": "present", "voice": voice,
                       "person": index % 3 + 1, "number": "singular" if index < 3 else "plural"}, answers, None
            yield {"pos": "verb", "form": "infinitive", "tense": "present", "voice": voice}, inf, None


def compare(vault, cache_path=DEFAULT_CACHE):
    data = load_cache(cache_path)
    requests, _, _, references = inventory(vault)
    summary = Counter(reference_lemmas=len(references), compared_lemmas=0, reference_cells=0,
                      exact=0, compatible=0, conflict=0, missing=0, quantity_differences=0)
    records = []
    for key, model in sorted(references.items(), key=lambda item: requests[item[0]]["query"]):
        request, record = requests[key], data["entries"].get(key)
        detail = {"word": request["query"], "pos": request["pos"], "cache_key": key,
                  "status": record["status"] if record else "not_imported", "differences": []}
        candidate = record.get("candidate") if record and record["status"] == "ready" else None
        if candidate:
            summary["compared_lemmas"] += 1
        counts = Counter()
        for features, expected, gender in reference_cells(request, model):
            summary["reference_cells"] += 1
            cell = lookup(candidate, **features) if candidate else None
            got = cell["forms"] if cell else []
            left, right = {vocab.normalize(f) for f in expected}, {vocab.normalize(f) for f in got}
            verdict = "missing" if not right else "exact" if left == right else "compatible" if left & right else "conflict"
            summary[verdict] += 1
            counts[verdict] += 1
            quantity_diff = False
            if cell and left & right and model.quantities_known:
                original = {vocab.normalize_keep(f) for f in expected}
                annotated = {vocab.normalize_keep(provider.quantified(f)) for f in cell["source_forms"]}
                quantity_diff = not bool(original & annotated)
                summary["quantity_differences"] += quantity_diff
            if verdict != "exact" or quantity_diff:
                detail["differences"].append({"features": features, "noun_gender": gender,
                    "verdict": verdict, "expected": expected, "imported": got,
                    "source_forms": cell["source_forms"] if cell else [], "quantity_difference": quantity_diff,
                    "missing_variants": sorted(left - right), "extra_variants": sorted(right - left)})
        detail["counts"] = dict(counts)
        records.append(detail)
    return {"comparison_version": 1, "summary": dict(summary), "records": records,
            "quantity_policy": "Imported grading forms omit quantity marks; raw prosodic annotations are retained for audit. Old reviewed quantities remain authoritative."}


def approve_entry(data, key):
    record = data["entries"].get(key)
    if record and record.get("pending_refresh"):
        record = deepcopy(record["pending_refresh"])
    if not record or record["status"] != "ready":
        raise CacheError(f"Cannot approve unavailable record: {key}")
    from morphology_cache import legacy_record
    from morphology_data import _nominal, _verb
    definition = legacy_record(record["request"], record["candidate"])
    pos = record["request"]["pos"]
    if pos == "verb":
        _verb(definition, f"cache approval: {key}")
    elif pos in ("noun", "adjective"):
        _nominal(definition, pos, f"cache approval: {key}")
    else:
        raise CacheError(f"No current quiz adapter for {pos}; the acquired table is retained for future topics")
    record["review_status"] = "approved"
    record["review_scope"] = "current_declension_and_present_drills"
    data["entries"][key] = record


def comparison_markdown(report, data):
    s = report["summary"]
    conflicts = [(r, d) for r in report["records"] for d in r["differences"] if d["verdict"] in ("conflict", "missing")]
    lines = ["# Morphology import accuracy audit", "",
        "Generated offline from the saved Collatinus responses. Imported answers were not filled or corrected using the old schema.", "",
        f"- Cached lookup identities: {len(data['entries'])} (including two pronouns and the locative lookup domī).",
        f"- Legacy-reference lemmas compared: {s['compared_lemmas']} / {s['reference_lemmas']}.",
        f"- Existing drill cells compared: {s['reference_cells']}.", "",
        "| Result | Cells |", "| --- | ---: |",
        f"| Same accepted forms, disregarding quantity marks | {s['exact']} |",
        f"| Overlapping accepted forms with variant differences | {s['compatible']} |",
        f"| Disjoint answers | {s['conflict']} |", f"| Missing answers | {s['missing']} |", "",
        f"At least one old accepted spelling occurs in {(s['exact'] + s['compatible']) / s['reference_cells']:.2%} of compared cells. "
        "This is agreement with the reference, not independent proof that every imported variant is correct.", "",
        f"Quantity annotations differ in {s['quantity_differences']} cells that otherwise overlap. "
        "The cache retains the raw annotations, but imported grading forms omit quantity marks and have quantities_known=false. "
        "The old schema remains authoritative for reviewed quantities.", "",
        "## Substantive differences", "", "| Word | Features | Old accepted answers | Imported answers |",
        "| --- | --- | --- | --- |"]
    for record, diff in conflicts:
        features = ", ".join(f"{k}={v}" for k, v in diff["features"].items() if k != "pos")
        lines.append(f"| {record['word']} | {features} | {', '.join(diff['expected'])} | {', '.join(diff['imported']) or '(missing)'} |")
    unparsed = sum(len(r.get("candidate", {}).get("unparsed", [])) for r in data["entries"].values())
    lines += ["", "The fēlīx neuter singular and the meus masculine vocative require correction/review before provider tables can replace the current keys. "
              "Allen & Greenough describes one-termination third-declension adjectives as sharing a nominative across genders, and gives mī for the vocative of meus:", "",
        "- [Third-declension adjective classification](https://dcc.dickinson.edu/grammar/latin/3rd-declension-adjectives-classification-and-paradigms)",
        "- [Possessive pronouns, §145](https://dcc.dickinson.edu/grammar/latin/possessive-pronouns-paradigm)", "",
        "## Coverage and use", "",
        f"The parser retained {sum(len(r.get('candidate', {}).get('cells', {})) for r in data['entries'].values())} feature-keyed cells. "
        f"It also recorded {unparsed} abbreviated finite tables as unparsed, preserving their raw responses. "
        "In particular, abbreviated compound perfect-passive paradigms are not complete six-person answer tables and have not been fabricated.", "",
        "Broader tense/mood/degree/participle data is acquired, but this audit validates only overlap with the existing drills. "
        "Other cached variants and future topics need their own reference checks.", "",
        "All imported records start unreviewed. Only explicit approval can enable a complete current-drill fallback. "
        "Bundled and user-supplied v1 definitions retain precedence. No imported answer silently replaces a reviewed current answer.", "",
        "## Reproduce", "", "```powershell", "python quiz/import_morphology.py --offline --compare --check", "```", "",
        "See morphology_comparison.json for every variant/quantity difference and cache key. "
        "Unchanged runs reuse stored responses; --offline makes network access impossible.", "",
        "Source: [Collatinus-web, Biblissima](https://outils.biblissima.fr/en/collatinus-web/index.php), "
        "Yves Ouvrard and Philippe Verkerk. Endpoint: the site's public inflection form handler. "
        "Each cache record includes source attribution, fetch time, response checksum and parser version.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=HERE.parent)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--retry-missing", action="store_true")
    parser.add_argument("--refresh", action="append", default=[], metavar="WORD_OR_KEY")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--reparse", action="store_true", help="Parse saved raw responses without API calls")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--check", action="store_true", help="Offline acquisition completeness check (does not grant linguistic approval)")
    parser.add_argument("--approve", action="append", default=[], metavar="CACHE_KEY", help="Explicitly approve a reviewed record for offline fallback")
    args = parser.parse_args()
    with cache_lock(args.cache):
        stats = import_tables(args.vault, args.cache, dry_run=args.dry_run, offline=args.offline or bool(args.approve) or args.check,
                              retry_errors=args.retry_errors, retry_missing=args.retry_missing, refresh=args.refresh,
                              limit=args.limit, reparse=args.reparse, progress=lambda text: print(text, flush=True))
        if args.approve:
            data = load_cache(args.cache)
            for key in args.approve:
                approve_entry(data, key)
            if not args.dry_run:
                save_json(args.cache, data)
        print(json.dumps(stats, sort_keys=True))
        if args.compare:
            report = compare(args.vault, args.cache)
            if not args.dry_run:
                save_json(args.cache.parent / "morphology_comparison.json", report)
                markdown = comparison_markdown(report, load_cache(args.cache))
                target = args.cache.parent / "MORPHOLOGY_AUDIT.md"
                if not target.exists() or target.read_text(encoding="utf-8") != markdown:
                    target.write_text(markdown, encoding="utf-8")
            print(json.dumps(report["summary"], sort_keys=True))
        if args.check:
            requests, _, _, _ = inventory(args.vault)
            entries = load_cache(args.cache)["entries"]
            unavailable = [r["query"] for key, r in requests.items() if entries.get(key, {}).get("status") != "ready"]
            if unavailable:
                print("Unacquired entries: " + ", ".join(unavailable))
                return 1
    return 1 if stats["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
