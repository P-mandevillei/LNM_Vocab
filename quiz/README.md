# Latin vocab quiz

Turns the chapter notes in this vault into random question sheets. There are
two front ends over the same engine (`vocab.py` — parsing, question building
and grading), so both behave identically:

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

## Retesting mistakes

The review page ends with **Retest the N I missed**, which starts a fresh quiz
over exactly those words — all of them, never a sample — each asked the way
round you got it wrong. Miss some of those and the new review offers a retest
of what's left, so you can keep going until it says *Nothing to retest*.

A word counts as missed if the meaning or any parsing field was wrong. **A
macron slip is not a mistake**: answers flagged `≈` are counted right and are
not retested. A word asked twice in one quiz (possible when the count exceeds
the number of words) is retested once.

Nothing is stored between quizzes — the retest works off the quiz you just
submitted, and a restarted server forgets everything.

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

## Files

- `vocab.py` — markdown parsing, question building, grading (shared)
- `streamlit_app.py` — the Streamlit front end
- `sheet.py` — builds the downloadable worksheet as one self-contained file
- `server.py` — the plain HTTP server and its JSON API
- `static/` — the plain server's pages (`index.html`/`app.js`/`style.css`,
  `print.html`/`print.js`/`print.css`)
- `../requirements.txt`, `../.streamlit/config.toml` — deployment config, at
  the vault root because that is the repo root Streamlit Cloud reads
