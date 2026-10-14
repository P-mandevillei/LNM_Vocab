# Morphology expansion: revised executive plan

Evaluation date: 14 October 2026. Status: the incremental importer and offline
cache adapter are implemented alongside the retained v1 schema. The actual
source run acquired 150 lookup records and compared all 147 existing lemmas.
Of 2,154 current-drill cells, 1,975 match exactly without quantity marks, 175
overlap with variant differences, four conflict and none are missing. An
unchanged rerun made zero API calls and left the cache bytes/time unchanged.
The source has quantity-notation differences and abbreviated future-topic
tables, so imported records remain unreviewed. The tester now gives explicit
chapter forms priority, then accepts either rule or cached answers, showing
disagreements on the answers page. The v1 schema and independent comparison
remain intact. Multi-selection of voice, tense and mood uses cached coverage
for topics outside the present-indicative rule engine.
See [importer instructions](IMPORT_MORPHOLOGY.md) and the
[accuracy audit](data/MORPHOLOGY_AUDIT.md) for implementation details and limits.

## Decision

Adopt a persistent, incremental answer-table cache generated before deployment.
Fetch a lemma's complete available paradigm once, validate and save it, and
reuse it for subsequent tests. On ordinary vocabulary updates, query only new
lemmas. Existing reviewed tables should not expire automatically.

This is highly feasible for this application. The difficult part is selecting
and validating a table provider, rather than storing the data or detecting new
vocabulary. Keep the current question selection, grading, retesting and UI;
introduce a shared table-lookup layer underneath both front ends.

“One import run” does not necessarily mean one HTTP request for the whole
vocabulary. Collatinus's current daemon accepts one word per inflection request.
Expect approximately one successful acquisition per distinct lemma unless the
chosen provider explicitly supports batch queries.

## Current scale and compatibility

The chapter files contain 191 entries. Today's morphology tester accepts 153
noun/adjective/verb occurrences, resolving to 147 distinct lemmas: 79 nouns,
18 adjectives and 50 verbs. Repeated verbs and early inflected aliases can
share a single table record. Noninflecting words and phrases need no direct
table request; pronouns and other future categories need their own support.

An in-memory serialization of all currently supported drill tables, including
all adjective genders, available voices, infinitives and accepted variants,
produced 2,154 cells: 69,664 bytes compact or 139,909 bytes indented JSON
(about 137 KiB). This is a measured current-scope example, not a size estimate
for every future Latin paradigm. A repository JSON file is sufficient at this
scale; a database is unnecessary.

The existing loader already handles JSON, custom paradigms, variants and
overrides. It can consume cached tables through an adapter for today's drills.
Broader tenses, moods, pronouns and nonfinite forms still require a generalized
schema and appropriate exercise views.

## Build and deployment workflow

Use an explicit import command locally before committing a chapter update.
A later CI job can run the same command. Do not put external lookups in the
Streamlit script, app startup, quiz creation or grading.

1. Read chapter files and resolve their dictionary entries to lemma identities.
2. Compare those identities and grammatical inputs with the saved cache state.
3. Reuse valid existing records; acquire only genuinely missing records.
4. Normalize responses, validate forms and restrictions, and report ambiguity
   or conflicts with reviewed answers.
5. Save checkpoints safely. Commit the chapter files and completed cache
   together, then deploy the resulting repository snapshot.
6. Both apps load that file and look up answers locally. Quizzes retain their
   original answer snapshots for exact retesting.

The recommended authoritative artifact is
`quiz/data/morphology_cache.json`, containing tables and their acquisition
state. Keep personal reviewed overrides in the existing root
`morphology.json`. Deterministic ordering makes new entries easy to review.

Streamlit Community Cloud copies repository files and starts the app from
them, so a committed cache is available on deployment:
[official file-organization documentation](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization).
Streamlit's [function cache](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data)
may accelerate reading this file, but should not be its authoritative storage.

If acquisition runs in CI, the updated artifact must be committed back through
a reviewed update or placed in durable storage. A temporary build workspace or
downloaded dependency cache alone does not preserve the vocabulary acquisition
state for the next build. Start with the local predeployment command; it avoids
a database, hosted morphology service and Git write credentials in the app.

## Cache identity and saved state

Store data once per canonical lemma, not once per chapter occurrence or quiz.
Use a provider lemma ID where available, together with part of speech and
dictionary-form disambiguation. Maintain a local index binding chapter forms
and reviewed aliases to those records.

Headword spelling alone is insufficient: macrons and dictionary forms can
distinguish different words. For example, the two nouns listed as unmarked
`os` have different genitives, `ōris` and `ossis`. Case/macron-insensitive
matching can find candidates, but must not merge ambiguous lemmas. Keep
canonical quantities in the answer data.

Each acquisition record should contain:

- Canonical lemma identity, dictionary forms/full principal parts and aliases.
- A fingerprint of grammatical input: dictionary forms, part of speech, gender,
  number restrictions and explicit lexical/sense restrictions. Preserve
  quantity distinctions. Chapter filenames, line numbers and ordinary English
  gloss formatting do not invalidate tables.
- Status, last attempt, failure reason and retry eligibility.
- Provider, source reference, fetch date, response checksum and parser version.
- Cache/schema version and an explicit inventory of covered grammatical forms.
- Accepted variants, unavailable forms, quantity confidence and review status.

Separate the chapter binding from the provider table record. A new occurrence
of an existing word in another chapter reuses its table without a request.
Sense-dependent choices, such as whether to offer a personal passive, belong
in the chapter binding or reviewed restrictions rather than being inferred
solely from a provider's formal table.

## Incremental update policy

| Situation | Normal import behavior |
| --- | --- |
| Same lemma, unchanged grammatical input, sufficient coverage | Reuse; zero API calls |
| Existing lemma appears in an additional chapter | Add/reuse binding; zero API calls |
| New distinct inflectable lemma | Acquire once, validate and cache |
| Noninflecting word or intentionally unsupported phrase | Record skipped reason; zero table calls |
| Previously ambiguous or not found, unchanged input | Preserve state and report; no repeated automatic query |
| Temporary timeout/server error | Record retry state; retry with limits when due |
| Changed dictionary forms or grammatical restrictions | Reconcile locally; flag affected record for review if necessary |
| Requested explicit refresh, source correction or missing new-topic coverage | Refresh selected records deliberately |

Successful records should have no time-based expiry. Track statuses such as
`ready`, `ambiguous`, `not_found`, `skipped` and `error`; absence of a table is
not the same as “not attempted.” An interrupted import must resume from
successful checkpoints. Permanent negative results can be retried explicitly
when the spelling, mapping or source has been corrected.

Use a single writer, atomic file replacement and schema validation so a failed
run cannot corrupt the previous cache. A failed refresh must retain the last
validated answer table. An unchanged rebuild should make zero requests and
leave the cache file unchanged, including timestamps.

A planned import tool should offer a dry-run change report, normal new-only
acquisition, targeted retries/refresh and an offline completeness check.
Release validation should reject newly required unanswered forms or require an
explicit, visible exemption. Existing reviewed drills remain usable when the
provider is unavailable.

## Extensibility and provider choice

Acquire the provider's full available paradigm initially, rather than only the
present forms currently displayed. Store grammatical features explicitly:
case, number, gender, degree, person, tense, mood, voice and nonfinite form.
Keep unavailable, not applicable and not yet acquired distinct. This supports
adding later exercise selections without refetching forms already stored.

“Only new vocabulary needs a request” is achievable for normal updates, not
an absolute forever guarantee. A provider correction, a newly supported topic,
or an incomplete original response can require selected old records to be
refreshed. Fetching broad paradigms up front minimizes that need. Cache/schema
changes should migrate or reparse existing data locally where possible;
optionally retain raw responses to support that.

[Collatinus at Biblissima](https://outils.biblissima.fr/en/collatinus-web/index.php)
remains the first provider to evaluate. It offers table generation with a
dictionary-derived lexicon. Its
[web handler](https://github.com/biblissima/outils.biblissima.fr/blob/master/collatinus-web/collatinus-web.php)
dispatches inflection requests to a daemon; the
[daemon source](https://github.com/biblissima/collatinus/blob/Daemon/src/server.cpp)
implements one-word `-F` requests returning tables. These are programmatic
interfaces, but a supported public bulk/JSON API has not been established.

A predeployment importer makes HTML normalization manageable: changes can be
detected and tested before publishing, while existing quizzes remain offline.
First confirm acceptable automated access, reuse/redistribution conditions,
table completeness, lemma disambiguation and quantity quality. If hosted access
is unsuitable, evaluate running Collatinus only on the import machine or CI
runner. The deployed Streamlit app would still need only the generated file.
Do not commit to hosting a new service until this evaluation is complete.

Retain the current curated data as authoritative for reviewed cells and use
explicit overrides for textbook conventions. Import conflicting provider
answers as review candidates, not silent replacements. Noun/adjective pair
answers are composed locally from individual cached tables; do not request or
store every possible word combination.

## Revised execution and acceptance

1. **Define the cache contract and compiler.** Export current reviewed paradigms
   into the proposed schema and add an offline lookup adapter. This can be done
   before choosing an API. Record present-only coverage honestly.
2. **Pilot one provider.** Import representative regular, irregular, mixed,
   plural-only and deponent lemmas. Compare with independent reference tables;
   establish access and data-reuse suitability.
3. **Implement incremental acquisition.** Add identity resolution, saved success
   and failure states, checkpoints, explicit retries and a dry-run report.
4. **Validate and deploy the baseline cache.** Acquire the broader available
   paradigms for existing lemmas, preserving reviewed answers and restrictions.
   Commit the resulting data with the chapters.
5. **Expand topics separately.** Add views and question options against cached
   feature coverage, preserving both current interfaces and exact retesting.

Required checks include: unchanged input makes zero API calls and zero file
changes; adding ten new distinct lemmas requests only those ten; duplicated
chapter words make no extra requests; ambiguous homographs are not merged;
interrupted imports resume; negative results are not queried on every build;
a failed refresh preserves old answers; missing future-topic coverage is
reported; and both apps grade and retest correctly with network access disabled.

The existing plan's source-validation and curriculum milestones remain valid.
The principal revision is to make durable, incremental acquisition a separate
predeployment step, with production quizzes depending only on versioned local
answer data.
