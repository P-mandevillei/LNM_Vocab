# Latin vocab quiz

Turns the chapter notes in this vault into random question sheets. There are
two front ends over the same engines (`vocab.py` for vocabulary and
`morphology.py` for declension/conjugation, question building and grading):

| | run it with | good for |
| --- | --- | --- |
| **Streamlit** (`streamlit_app.py`) | `streamlit run quiz/streamlit_app.py` | deploying to the web; phones |
| **Plain server** (`server.py`) | `python quiz/server.py` or `run.bat` | local use with no install at all |

## Running the Streamlit app

```
pip install -r requirements.txt
streamlit run quiz/streamlit_app.py
```

It opens <http://localhost:8501>. Chapters come from the folder above `quiz/`,
or from `$LATIN_VAULT` if that is set. Editing a chapter is picked up
automatically; **Reload** in the sidebar forces a re-read.

Both **Vocabulary** and **Declension & conjugation** tabs are available in
Streamlit. They share the sidebar's chapter selection, question count,
Exhaustive and Shuffle order. The morphology tab has its own entry-type,
verb-voice and adjective-gender selectors. Vocabulary Mode and Also test
parsing apply only to the vocabulary tab. Each tab keeps its own quiz, results
and missed entries, so starting or retesting one does not replace the other.
Morphology tables use the same chapter 10 definitions, live `morphology.json`
overrides and original-answer retesting as the plain server.

## Accounts and saved history

Use **Sign in with Google** in the sidebar before starting a test. Submitted
tests save to your account in Firebase Cloud Firestore. **Page → Account**
shows historical scores, individual test details, and buttons to retest every
entry or just the incorrect entries. The recent-history summary defaults to
the latest 10 tests, with choices of 5, 10, 20 or 50. Recent mistake practice
combines distinct incorrect question variants from that window, separately
for vocabulary and morphology, even if a later test answered them correctly.

Stored records contain entry references, score totals, incorrect-field
positions and unfamiliar flags; submitted answers and expanded answer tables
are omitted. Save failures remain queued in the current browser session with
an explicit retry button. Guest practice and record downloads remain available.

Google OAuth and Firestore service-account credentials are configured through
Streamlit secrets. Follow [Account setup](ACCOUNTS_SETUP.md) for Community
Cloud instructions and secure credential-file handling. Sign-in is disabled
until setup is complete. Do not commit real credentials or paste them into chat.

## Deploying to Streamlit Community Cloud

The repo is already set up for it — `requirements.txt` and `.streamlit/` sit at
the vault root, next to the chapter files.

1. `git init && git add . && git commit -m "Latin vocab quiz"` in the vault.
2. Push it to a GitHub repo (private is fine — you authorise Streamlit to read it).
3. On <https://share.streamlit.io>, create an app from that repo with
   **main file path** `quiz/streamlit_app.py`.

Two things to know. The chapters are baked in at push time, so a new chapter is
only asked about after you commit and push it — the Obsidian Git plugin can do
that for you. And a deployed app is reachable by anyone with the link unless
you restrict it to invited emails in the app's settings.

For an existing deployment, commit and push the updated Streamlit files to
the branch selected by the app. Rebooting the cloud app runs that deployed
branch; it does not pick up unpushed local changes. Keep `quiz/streamlit_app.py`
as the main file and include `quiz/streamlit_morphology.py`, the morphology
engine/data files and chapter files in the same repository.

## Running the plain server

Double-click `run.bat`, or from a terminal:

```
python quiz/server.py
```

It prints a URL (default <http://localhost:8765>) and opens the browser for you.
(`--port N` picks a port, `--vault PATH` reads chapters from somewhere else.)
Stop it with Ctrl+C. Nothing leaves the machine — the server binds to
`127.0.0.1` only.

Chapter files are re-read on every request, so after editing a chapter just
click **reload files** (or start a new quiz). No restart needed.

## Chapter file format

Any `.md` file in the vault (outside `.obsidian` and this `quiz/` folder) is
picked up. Bold headings set the part of speech; each entry is
`latin forms – English meaning`:

```markdown
**NOUNS**
aqua, aquae, f. – water

**VERBS**
amō, amāre, amāvī, amātum – to love

**ADJECTIVES**
magnus, magna, magnum – large, great

**PRONOUNS**
hic, haec, hoc – this

**ADVERBS**
bene – well
```

Separator may be an en dash, em dash, or hyphen with spaces around it.
Commas separate Latin forms; a trailing `m.` / `f.` / `n.` is read as gender.
Commas and semicolons in the English gloss are read as alternative meanings —
any one of them is accepted as an answer.

Headings are matched by keyword, so `**ADJECTIVES (1st/2nd declension)**`,
`**VERB**`, `**DEPONENT VERBS**` and `**PROPER NOUNS**` all land in the right
category. Recognised: noun, pronoun, verb, adjective, adverb, participle,
numeral, preposition, conjunction, interjection, phrase. Anything else still
works — such words are asked for their meaning but not parsed.

These notations are understood as well:

| written | read as |
| --- | --- |
| `timeō, timēre, timuī, ____` | a verb with no 4th principal part — the blank is never asked for (`-`, `--`, `?` work too) |
| `castra, castrōrum, n. pl.` | neuter plural; the genitive is asked as *genitive plural* |
| `cum + ablative` | the preposition `cum`, which takes the ablative |
| `iubeō, iubēre, iussī, iussum + accusative + infinitive` | four principal parts; the `+ …` is kept as a note, not asked |
| `ē (ex) + ablative` | either `ē` or `ex` is accepted |
| `dō, dăre, dedī, dătum – to give (note the short stem vowel)` | the parenthetical note is optional in an answer, and left out of English → Latin prompts |

## What gets asked

- **Latin → English** — write the meaning of the headword.
- **English → Latin** — write the Latin word for a meaning. If two words in
  the selected chapters share a gloss (e.g. `amat` and `amō` both "love"-ish),
  either is accepted.
- **Mixed** — each question picks a direction at random.

By default the quiz draws *Number of questions* words at random. Tick
**Exhaustive** to be asked every word in the selected chapters instead, once
each — the count is then ignored (and greyed out). **Shuffle order** off asks
them in the order the chapters list them, which keeps parts of speech grouped.
Both options apply to printable sheets too.

For English → Latin the headword is the expected answer, but writing out the
whole listing (`magnus, magna, magnum`, or `puella, puellae, f.`) is accepted
too.

With *Also test parsing* on, a question adds the forms the chapter actually
lists for that word — never a form the chapter doesn't give, so nothing has to
be filled in with placeholders:

| listed as | extra fields asked |
| --- | --- |
| `aqua, aquae, f.` | genitive singular, gender |
| `amō, amāre, amāvī, amātum` | 2nd, 3rd, 4th principal parts |
| `veniō, venīre, vēnī` | 2nd, 3rd principal parts — no 4th asked |
| `possum, posse` | 2nd principal part only |
| `sum` | none |
| `magnus, magna, magnum` | feminine, neuter (the masculine is the prompt/answer, so all three genders are covered) |
| `omnis, omne` | neuter |
| `fēlīx, fēlīcis` | genitive singular |
| `hic, haec, hoc` | feminine, neuter |
| `ego, meī` | genitive singular |
| `bene, melius, optimē` | comparative, superlative |
| `castra, castrōrum, n. pl.` | genitive plural, gender |
| `cum + ablative` | the case it takes (English → Latin only — the other direction shows it in the prompt) |
| `diū`, `et`, `ego` | none |

Adjectives and pronouns use the same rule: a three-form listing is read as the
masculine/feminine/neuter set. A two-form listing is read as neuter when the
second form ends in `-e` (`omnis, omne`) and as a genitive otherwise
(`fēlīx, fēlīcis`, `ego, meī`) — that covers the usual textbook listings, but
it is a guess about intent rather than something the format states.

## Printable sheets

A worksheet of numbered prompts with ruled blanks to write on, the same parsing
fields the quiz would ask, and an answer key on its own page. It uses the same
chapters, mode, count, *Exhaustive*, *Shuffle order* and parsing settings as
the quiz.

In **Streamlit**, open *Printable sheet*, pick the answer key / columns /
spacing, press **Build sheet**, then **Download sheet**. Open the downloaded
file and print it (or save as PDF) — the toolbar on the sheet still toggles the
answer key, spacing and two-column layout, and its **Print** button is the one
to use. The in-app *Preview* is only for looking; printing from it would print
the whole Streamlit page.

In the **plain server**, *Printable sheet…* opens the same worksheet in a new
tab, where the toolbar additionally offers **New draw** for a fresh random
sheet. That page's URL holds all of its settings, so it can be bookmarked.

## Grading

Macrons are optional: `poetae` for `poētae` is counted correct and flagged `≈`
so you know one was missing. Case and punctuation are ignored. For English,
`to love` / `love` and `he/she/it loves` / `loves` all count. Gender accepts
`f.` / `f` / `fem` / `feminine` (plus `pl.` / `plural` where the chapter says
so), and a preposition's case accepts `abl` / `abl.` / `ablative`.

Answers live on the server until you submit, so they aren't sitting in the page
source while you work.

## Test records

Both Streamlit tabs offer **Download test record** during a test and on its
results page. New records use compact version 2 JSON: the test configuration
and an ordered list of chapter entry references (`filename:line`) with the
choices made for each occurrence. Vocabulary saves its question direction;
morphology saves its entry type, chosen gender or verb voice/tense/mood, and
the actual adjective reference for a pair. Repeated words and their exact
order are preserved. Tables, labels and answer keys are reconstructed rather
than copied into every record.

The original chapter markdown files must remain installed and unchanged.
Restoration uses the current morphology definitions, overrides and imported
tables; catalog and engine revisions are not retained. Original answer keys
are not archived in new records.

Completed downloads also contain a compact result: final score totals,
incorrect question/field positions, and any unfamiliar entry indices. They
never retain submitted answer text or expanded grading objects.

Use **Test records → Upload test record** in the Streamlit sidebar. Uploading
restores the controls and starts the recorded questions as a new attempt,
with blank answers, cleared unfamiliar marks and no previous result attached.
Streamlit tells you which tab contains the restored test. Missing entries or
invalid records leave the current test and controls unchanged.

Streamlit still accepts older version 1 snapshots, including their embedded
answer keys, even without their original chapters. The legacy plain server's
version 1 export and restore behavior is unchanged; version 2 records are for
Streamlit.

The current app requires Streamlit 1.65 or newer for account login and practice
tab navigation. Downloading a record does not rerun the app and discard answers
in progress, a feature available since 1.43. See the
[Streamlit release notes](https://docs.streamlit.io/develop/quick-reference/release-notes/2025#version-1430).

## Unfamiliar entries and review

Tick **Unfamiliar** beneath any vocabulary question or morphology table
during a test or re-test. After submission, all marked entries appear at the
top, regardless of whether their answers were correct. The remaining entries
are in a collapsed **Remaining entries** menu: wrong answers first, followed
by correct answers (including optional-macron slips). Original question
numbers are retained. Marking an entry does not change its score.

## Retesting mistakes

The review page offers **Retest entries** with three selections and their
counts: **Wrong entries only**, **Unfamiliar entries only**, or **Unfamiliar +
wrong entries**. Wrong entries are the default. The re-test covers all selected
entries, never a sample; an entry that is both wrong and unfamiliar is included
once. Vocabulary words repeat their original direction and parsing fields;
morphology entries repeat their whole original table. Original answer keys
are retained even after chapter edits. Each new attempt clears unfamiliar
marks so you can mark the entries that remain unfamiliar.

A word counts as missed if the meaning or any parsing field was wrong. **A
macron slip is not a mistake**: answers flagged `≈` are counted right and are
not retested. A word asked twice in one quiz (possible when the count exceeds
the number of words) is retested once.

The active session keeps the latest attempt for re-testing. A restarted server
forgets its sessions; download a test record to preserve and replay an attempt.

## Differences between the two front ends

The questions, parsing, grading, retesting and worksheet content are identical.
What differs is the shell around them:

- **Keyboard.** The plain server moves to the next box on **Enter** and submits
  on **Ctrl+Enter**. In Streamlit you tab between boxes.
- **Printing.** The plain server opens the sheet in a tab; Streamlit downloads
  it (see above).
- **Settings memory.** The plain server remembers your chapters and options in
  the browser between visits. Streamlit resets to the defaults each session.
- **Install.** The plain server needs nothing but Python; Streamlit needs the
  package installed.

## Declension and conjugation tab (plain server)

The **Declension & conjugation** tab is a separate page at `/morphology.html`.
The vocabulary quiz, its settings, printing and retest interface keep their
existing behavior. No extra package or network connection is needed.

Select chapters and any of four entry types:

- A noun's six cases in singular and plural.
- An adjective's six cases in a specified gender, singular and plural.
- A verb conjugation chosen from multiple voices (active/passive), six tenses
  and three moods (indicative/subjunctive/imperative), plus an infinitive in
  the same voice. Present indicative in both voices remains the default.
- A noun and an adjective declined together, agreeing in gender, case and
  number. Enter both words in each cell; either word order is accepted.

**Number of entries** counts whole tables, not individual cells. Random draws
use the vocabulary quiz's sampling rule: sample without replacement until
the pool is exhausted, then repeat if more entries were requested. Each
adjective entry gets one gender and each verb entry gets one supported
voice/tense/mood combination chosen from the selections. Exhaustive refers
to words, not every combination. The infinitive is perfect for perfect,
pluperfect and future perfect tables, and present otherwise. Unsupported
combinations are skipped; nonexistent imperative persons are disabled.

The question shows one lemma per word, including one lemma for each word in
a pair. Translations and full dictionary entries appear only on the answers
page. Answer sources and warnings are withheld until submission.

**Exhaustive** covers every eligible chapter entry once per selected type.
For pairs it covers every eligible noun and adjective at least once, cycling
the shorter list instead of testing every possible combination. If standalone
nouns/adjectives and pairs are both selected, words also appear in their
standalone tables. With shuffle off, entries follow chapter order
within each type. Only words from the selected chapters can be drawn; a
local lexicon supplies metadata for those words, including early chapter
forms such as `amat` → `amō`.

Each available cell is graded individually. A table counts as correct only
if every available cell is correct. Missing or wrong macrons are flagged but
count as correct. **Retest the N I missed** repeats the whole missed tables
with the same adjective gender, verb voice/tense/mood, and noun–adjective pair. Exact
repeats of the same missed problem are retested once. Retests use the original
answer key even if a chapter is edited mid-session.

Plural-only nouns and adjectives have disabled singular cells, including in
agreement pairs. Common-gender nouns are given
an explicit gender for each problem. Verbs whose chapter sense lacks a full
personal passive paradigm are offered only in the active voice; passive-only
draws exclude them. This includes `sum`, `possum`, `soleō`, intransitive senses,
and `dō`, whose first-person passive is absent from the reference paradigm.

Chapters 1–10 supply 79 supported noun entries, 18 adjectives and 56
verb entries. Chapter 10's 19 individual inflectable words are all supported:
7 nouns, 5 adjectives and 7 verbs. Selecting all four entry types produces
26 exhaustive entries, including 7 noun–adjective pairs. Its third-declension
adjectives (`ācer`, `celeber`, `fēlīx`, `fortis`) work in all genders, and its
mixed third-conjugation verbs (`capiō`, `cupiō`, `fugiō`) include the matching
present infinitive. `paucī` and its agreeing pairs are plural only; `fugiō`
(flee) and `pugnō` (fight) are active only for their chapter senses. `deus`
accepts its irregular plural variants and the vocative `deus` or late `dee`.
The phrase `consilia capere` and the conjunction `nec` remain vocabulary items.

The unavailable-entry disclosure identifies phrases and
incomplete dictionary entries rather than silently inventing their forms.
Regular new words can be added in the usual chapter format. Extra inflection
metadata, exceptions, variants and complete irregular answer tables go in
**`morphology.json` in the chapter folder**, independently of Python code.
Changes apply to the next quiz or pool refresh without restarting the server.
The generator supports all five noun declensions, first/second- and
third-declension adjectives, and the four regular verb conjugations including
third-conjugation `-iō` verbs. Ambiguous classes still need explicit metadata;
full custom tables can represent further irregular patterns.
See [Adding vocabulary and answer keys](MORPHOLOGY.md) for definitions and
copyable examples. Regular verbs with a macronized `-āre`, `-ēre` or `-īre`
infinitive can be recognized directly for active quizzes; an explicit lexical
definition enables their personal passive.
For unreviewed vocabulary, macrons are accepted without issuing quantity
corrections. Comparative/superlative adjectives and locatives are not part of
this six-case tester.

The [incremental table importer](IMPORT_MORPHOLOGY.md) fetches new
vocabulary before deployment and caches source responses and parsed tables.
Subsequent runs reuse existing words. The v1 lexicon and personal overrides
are retained. The tester reads ready cached tables independently of the v1
loader's approval workflow. No quiz or grading operation calls the API.

Each cell uses this policy:

1. A form explicitly listed in that chapter entry takes precedence. Its exact
   spelling is the answer, with the existing optional-macron policy. Noun
   nominatives/genitives, adjective gender forms (or nominative/genitive for
   one-termination adjectives), and applicable verb principal parts are mapped
   to their own grammatical cells. Other cells are not overridden by inference.
2. Otherwise, either a rule-generated or imported spelling is accepted. A
   missing rule adds no check; cached forms alone can supply the answer.
3. The answers page displays the accepted answer, a collapsed **Answer sources**
   menu with the detailed chapter/rule/importer forms, and
   **⚠** whenever rule/importer spelling variant sets differ, even when they
   overlap or a chapter form takes precedence. Provider quantity marks are
   audit data, not trusted macron corrections. Pair components follow this
   policy independently, and valid forms from different schemes can be combined.

The rule engine currently supplies declensions and present indicative;
additional finite tenses/moods come from the cache. Some perfect-system
passive tables are abbreviated by the source and remain unparsed, so those
combinations are unavailable. See [the source audit](data/MORPHOLOGY_AUDIT.md).

Answer generation uses local stems, endings, lexical restrictions and
exceptions. The reference rules and fixtures follow Allen & Greenough,
available through Dickinson College Commentaries:

- [Number and case](https://dcc.dickinson.edu/grammar/latin/number-and-case)
- [Third-declension i-stem forms](https://dcc.dickinson.edu/grammar/latin/3rd-declension-summary-i-stem-forms)
- [Third-declension adjective paradigms](https://dcc.dickinson.edu/grammar/latin/3rd-declension-adjectives-classification-and-paradigms)
- [The irregular declension of deus](https://dcc.dickinson.edu/grammar/latin/2nd-declension-case-forms)
- [Mixed third-conjugation verbs and infinitives](https://dcc.dickinson.edu/sites/default/files/3rd_conj_io_verbs_pres.pdf)
- [First/second-declension adjectives](https://dcc.dickinson.edu/grammar/latin/1st-and-2nd-declension-adjectives-%C4%81-o-stems)
- [Present verb endings](https://dcc.dickinson.edu/sites/default/files/verb_personal_endings_pres.pdf)
- [The irregular present of dō](https://dcc.dickinson.edu/sites/default/files/d%C5%8D_d%C4%83re_pres.pdf)
- [Impersonal passives](https://dcc.dickinson.edu/grammar/latin/impersonal-verbs)

Run the reference-form, grading/retest, selection and HTTP regression tests:

```sh
python -B -m unittest discover -s quiz -p 'test_*.py'
```

## Files

- `vocab.py` — markdown parsing, question building, grading (shared)
- `morphology.py` — local morphology answer keys, table generation and grading
- `morphology_data.py` — validates and loads lexical definitions and overrides
- `morphology_lexicon.json` — bundled dictionary forms, classes and exceptions
- `../morphology.json` — personal additions and answer-key overrides, reloaded live
- `MORPHOLOGY.md` — guide to extending answer keys for future chapters
- `test_morphology.py` — reference paradigms and HTTP regression tests
- `test_morphology_extensions.py` — new classes, custom tables and live reload tests
- `test_morphology_ch10.py` — every chapter 10 table, agreement and HTTP workflow
- `test_streamlit.py` — Streamlit tabs, forms, independent sessions, grading/retesting and reloads
- `streamlit_app.py` — the Streamlit front end
- `streamlit_morphology.py` — the Streamlit morphology tab over the shared engine
- `quiz_record.py` — portable record validation and review/re-test selection
- `streamlit_records.py` — shared Streamlit record controls and review grouping
- `streamlit_accounts.py` — Google login, save queue and account dashboard
- `account_history.py` — stable account IDs, compressed saved attempts and cumulative practice
- `firestore_history.py` — account-scoped Firestore reads, pagination and idempotent writes
- `configure_accounts.py` — builds ignored secrets from downloaded credential files
- `ACCOUNTS_SETUP.md` — Google/Firebase configuration and live verification instructions
- `test_account_history.py`, `test_streamlit_accounts.py` — account isolation, storage and dashboard workflows
- `test_records.py` — record replay, validation and re-test selection regressions
- `test_reference_records.py` — compact record reconstruction, sparse results and size regressions
- `sheet.py` — builds the downloadable worksheet as one self-contained file
- `server.py` — the plain HTTP server and its JSON API
- `static/` — the plain server's pages (`index.html`/`app.js`/`style.css`,
  `print.html`/`print.js`/`print.css`)
- `../requirements.txt`, `../.streamlit/config.toml` — deployment config, at
  the vault root because that is the repo root Streamlit Cloud reads
