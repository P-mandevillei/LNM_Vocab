# Incremental morphology importer

The importer runs before deployment and saves Collatinus's tables for offline
use. It supplements the existing schema; it does not replace
`morphology_lexicon.json` or the root `morphology.json`.

## Run an update

```
./.venv/Scripts/python.exe quiz/import_morphology.py --compare
```

From the repository root:

```powershell
python -m pip install -r quiz/requirements-import.txt
python quiz/import_morphology.py --dry-run
python quiz/import_morphology.py --compare
python quiz/import_morphology.py --offline --check
```

If using the local virtual environment, replace `python` with
`.\.venv\Scripts\python.exe`. The import-only dependency uses the operating
system's trusted certificate store. HTTPS certificate verification stays on.
Neither quiz front end needs this dependency to read the cache.

The first import makes one request per distinct lookup identity, at most one
request per second. Later normal updates fetch new identities only. Chapter
duplicates, early aliases recognized by the old lexicon and shorter verb
dictionary listings reuse the same request. Full principal parts are retained
as metadata. English gloss changes do not invalidate answer tables.

The actual initial run saved 150 lookup records from chapters 1–10: the 147
lemmas already supported by the morphology tester, two personal pronouns and
the `domī` lookup. Noninflecting words and phrases are recorded as skipped.
An unchanged normal rerun made zero API calls and did not change the cache's
bytes or modification time.

## Files and saved state

- `data/morphology_cache.json`: versioned acquisition records, grammatical
  identity, full parsed feature-keyed cells, chapter bindings, restrictions,
  review status and skipped entries.
- `data/collatinus_raw/`: content-addressed source responses for independent
  inspection and reparsing without another request.
- `data/morphology_comparison.json`: every overlap, variant difference,
  conflict and quantity discrepancy against the retained v1 engine.
- `data/MORPHOLOGY_AUDIT.md`: readable accuracy and coverage report.

Each record includes the source URL, fetch date, checksum and parser version.
The cache distinguishes `ready` (parsed and resolved), `ambiguous`, `not_found`
and temporary `error` states. **Ready does not mean linguistically approved.**
Successful and permanent negative results do not expire. Temporary errors have
a retry time; explicit retry flags can retry them sooner.

Atomic replacement and a single-writer lock protect the cache. Successful
acquisitions are checkpointed after each word, so interrupted imports resume.
Windows sync/indexing file locks receive bounded retries. Failed refreshes
retain the old table. A changed refresh of an approved table remains under
`pending_refresh` until explicitly approved.

Commit the chapters, cache and source responses together for deployment. The
Streamlit app and plain server only read them; they never fetch tables while
creating, grading or retesting a quiz. Custom vaults can use a cache named
`morphology_cache.json` inside the vault.

## Inspect, retry and refresh

```powershell
# Limit acquisition for a pilot/resume; already cached words do not count.
python quiz/import_morphology.py --limit 10

# Retry temporary errors or unresolved/not-found words explicitly.
python quiz/import_morphology.py --retry-errors
python quiz/import_morphology.py --retry-missing

# Deliberately re-fetch one saved identity.
python quiz/import_morphology.py --refresh capio --compare

# Reparse saved responses without network access.
python quiz/import_morphology.py --offline --reparse --compare

# Reparse only named identities using their existing response files.
python quiz/import_morphology.py --offline --reparse --refresh capio --compare

# Alternate chapter folder/cache artifact.
python quiz/import_morphology.py --vault PATH --cache PATH/morphology_cache.json --compare
```

`--check` is an offline acquisition-completeness check. It fails for missing,
unresolved or failed lookup records. It does not certify every source answer,
approve new vocabulary or promise coverage for every future tense/topic.

Dictionary resolution checks nominatives/genitives, adjective dictionary forms
and present infinitives in their proper grammatical slots. It does not match
an arbitrary inflected spelling to a dictionary form. Quantity-distinct
homographs remain separate; genuinely equivalent tables may record multiple
equivalent source IDs. Consonantal `j` and textbook `i` are retained as spelling
variants where needed.

## Quiz policy and retained v1 approval workflow

The initial acquisition leaves all records **unreviewed**. The tester now
uses ready imports as an independent answer scheme: an explicitly listed
chapter form wins; otherwise either rule or importer forms count as correct.
It shows spelling/variant disagreements with **⚠** on the answers page.
Additional tenses/moods use cached forms when no rule exists. This does not
modify or replace the v1 schema, its definitions, or the independent audit.

The separate v1 loader still supports approval when a cache table should
serve as a missing legacy definition. After inspecting the record, copy its key
from the comparison JSON and explicitly approve it:

```powershell
python quiz/import_morphology.py --offline --approve CACHE_KEY
```

Approval validates that the record can supply the complete current-drill
projection. It covers the current declension/present drills, not all acquired
future topics. If a pending refresh exists, this adopts that reviewed refresh.
Approval itself makes no API calls. The legacy projection preserves recorded
passive restrictions. The tester likewise honors reviewed chapter-sense
restrictions; an unclassified word can use its available cached voices.

The loader uses explicitly approved cached tables only for words without
bundled definitions. Bundled v1 definitions replace cached definitions as a
whole; personal v1 overrides retain precedence. A user can still add regular
classification metadata or complete custom keys in `morphology.json` exactly
as before. The offline adapter accepts new approved tables for declensions and
present conjugations. The tester reads broader source cells separately,
without projecting them into v1. Multiple distinct approved homographs cannot be
collapsed into one v1 headword key; they require an explicit legacy mapping.

Imported grading forms intentionally omit quantity marks and have
`quantities_known: false`. The source's macrons/breves are preserved separately
for audit. The current reference quantities are not overwritten.

## Accuracy findings and limits

The real comparison covers all 147 existing lemmas and 2,154 current-drill
cells: 1,975 have identical accepted spellings without quantity marks, 175
overlap with different variants, four disagree and none are missing. The
disagreements are the neuter singular nominative/accusative/vocative of
`fēlīx` (source `felice`) and masculine vocative singular of `meus` (source
`mee`). Those tables cannot replace the current keys as supplied.

Quantity annotations differ in 1,002 otherwise overlapping cells. Agreement
with the old schema is a regression comparison, not independent proof that
all additional historical/poetic variants are suitable for this textbook.

The cache contains 15,726 parsed cells, including later tenses, moods,
adjective degrees and nonfinite forms. It also preserves 100 abbreviated
finite tables as unparsed. In particular, the provider abbreviates compound
perfect-passive paradigms instead of supplying all six persons. No missing
persons have been guessed. Other topics need their own completeness and
reference checks before being exposed as quizzes.

Source: [Collatinus-web, Biblissima](https://outils.biblissima.fr/en/collatinus-web/index.php),
Yves Ouvrard and Philippe Verkerk. See the generated audit for independent
grammar references and the full comparison for each source form.

## Verification

```powershell
python -m unittest discover -s quiz -p 'test_*.py'
```

The importer tests are offline. They use saved live-response fixtures and a
fake provider to check ten-new-word acquisition, zero-call unchanged updates,
negative caching, interruption recovery, failed refreshes, atomic replacement,
homographs, review gating, old-schema precedence and grading/retesting from a
new cached third-declension noun. Install the main `requirements.txt` as well
to include Streamlit interaction tests.
