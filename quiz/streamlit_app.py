"""Latin vocab quiz -- Streamlit front end.

Run locally:      streamlit run quiz/streamlit_app.py
Deploy:           point Streamlit Community Cloud at this file in the repo.

All the parsing, question building and grading lives in vocab.py, which this
shares with the plain-Python server (server.py); this module is only the UI.
Chapter markdown is read from the folder above this one, or from $LATIN_VAULT.
"""

from __future__ import annotations

import os
import random
from html import escape
from pathlib import Path

import streamlit as st
from streamlit.components.v1 import html as html_component

import vocab
from sheet import MODE_LABEL, render_sheet

HERE = Path(__file__).resolve().parent
VAULT = Path(os.environ.get("LATIN_VAULT") or HERE.parent).resolve()

MODES = ["la_to_en", "en_to_la", "mixed"]
MODE_HELP = {
    "la_to_en": "Latin → English",
    "en_to_la": "English → Latin",
    "mixed": "Mixed",
}
VERDICT = {
    "correct": ("ok", "✓", ""),
    "macrons": ("warn", "≈", "macrons missing / wrong"),
    "wrong": ("bad", "✗", ""),
}

st.set_page_config(page_title="Latin Vocab Quiz", page_icon="\U0001f4dc",
                   layout="centered")

CSS = """
<style>
.qhead { display: flex; gap: .5rem; align-items: baseline; flex-wrap: wrap;
         font-size: .8rem; opacity: .75; margin-bottom: .1rem; }
.qnum { font-weight: 700; opacity: 1; }
.chip { font-size: .7rem; text-transform: uppercase; letter-spacing: .06em;
        border: 1px solid currentColor; border-radius: 999px;
        padding: .02rem .5rem; opacity: .8; }
.prompt { font-size: 1.35rem; margin: .1rem 0 .4rem; }
.prompt.latin { font-style: italic; }
.result { padding: .1rem 0 .2rem .8rem; border-left: 3px solid transparent;
          margin-bottom: 1rem; }
.result.ok { border-left-color: #1f7a4d; }
.result.warn { border-left-color: #a06a12; }
.result.bad { border-left-color: #a32626; }
.row { display: flex; gap: .6rem; align-items: flex-start; padding: .35rem .6rem;
       border-radius: 7px; margin-bottom: .3rem; }
.row.ok { background: rgba(31,122,77,.13); }
.row.warn { background: rgba(160,106,18,.15); }
.row.bad { background: rgba(163,38,38,.13); }
.mark { font-weight: 700; width: 1rem; }
.row.ok .mark { color: #1f7a4d; }
.row.warn .mark { color: #a06a12; }
.row.bad .mark { color: #a32626; }
.rowbody { flex: 1; min-width: 0; }
.rowlabel { font-size: .72rem; text-transform: uppercase; letter-spacing: .06em;
            opacity: .7; }
.line { display: flex; gap: .5rem; align-items: baseline; }
.tag { font-size: .68rem; text-transform: uppercase; letter-spacing: .06em;
       opacity: .6; min-width: 3.4rem; }
.val { overflow-wrap: anywhere; }
.line.right .val { font-weight: 600; }
.note { font-size: .76rem; color: #a06a12; }
.fullentry { margin-top: .35rem; font-size: .85rem; opacity: .7;
             font-style: italic; }
.bigscore { font-size: 2.2rem; font-weight: 700; line-height: 1.1; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# chapter loading
# ---------------------------------------------------------------------------

def vault_stamp() -> tuple:
    """Changes whenever a chapter file is edited, so the cache reloads."""
    return tuple(sorted(
        (p.name, p.stat().st_mtime_ns, p.stat().st_size)
        for p in vocab.find_markdown_files(VAULT)
    ))


@st.cache_data(show_spinner=False)
def load_chapters(_stamp: tuple) -> dict[str, list[vocab.Entry]]:
    return vocab.load_vault(VAULT)


def pool_for(chapters: dict, files: list[str]) -> list[vocab.Entry]:
    return [e for name, entries in chapters.items() if name in files
            for e in entries]


# ---------------------------------------------------------------------------
# state helpers
# ---------------------------------------------------------------------------

def init_state() -> None:
    st.session_state.setdefault("view", "setup")
    st.session_state.setdefault("quiz", None)
    st.session_state.setdefault("quiz_title", "Question sheet")
    st.session_state.setdefault("quiz_files", [])
    st.session_state.setdefault("quiz_mode", "mixed")
    st.session_state.setdefault("quiz_parsing", True)
    st.session_state.setdefault("results", None)
    st.session_state.setdefault("missed", [])
    st.session_state.setdefault("sheet", None)


def clear_answers() -> None:
    """Drop the text_input values of a finished quiz."""
    for key in [k for k in st.session_state if k.startswith("ans_")]:
        del st.session_state[key]


def begin_quiz(questions: list[dict], title: str, files: list[str],
               mode: str, parsing: bool) -> None:
    clear_answers()
    st.session_state.update(
        view="quiz", quiz=questions, quiz_title=title, quiz_files=list(files),
        quiz_mode=mode, quiz_parsing=parsing, results=None, missed=[],
    )


# ---------------------------------------------------------------------------
# sidebar: what to be asked
# ---------------------------------------------------------------------------

def sidebar(chapters: dict) -> dict:
    names = list(chapters)
    with st.sidebar:
        st.subheader("Chapters")
        if "files" not in st.session_state:
            st.session_state.files = names

        c1, c2, c3 = st.columns(3)
        if c1.button("All", use_container_width=True):
            st.session_state.files = names
            st.rerun()
        if c2.button("None", use_container_width=True):
            st.session_state.files = []
            st.rerun()
        if c3.button("Reload", use_container_width=True,
                     help="Re-read the chapter files from disk"):
            load_chapters.clear()
            st.rerun()

        files = st.multiselect("Chapters", names, key="files",
                               label_visibility="collapsed")
        for name in files:
            by_pos: dict[str, int] = {}
            for e in chapters[name]:
                by_pos[e.pos] = by_pos.get(e.pos, 0) + 1
            breakdown = ", ".join(f"{n} {pos}{'' if n == 1 else 's'}"
                                  for pos, n in by_pos.items())
            st.caption(f"**{name}** — {breakdown}")

        st.subheader("Mode")
        mode = st.radio("Mode", MODES, index=2, key="mode",
                        format_func=lambda m: MODE_HELP[m],
                        label_visibility="collapsed")

        st.subheader("Options")
        exhaustive = st.checkbox(
            "Exhaustive", key="exhaustive",
            help="Ask every word in the selected chapters, once each")
        count = st.number_input("Number of questions", 1, 500, 10, key="count",
                                disabled=exhaustive)
        shuffle = st.checkbox(
            "Shuffle order", value=True, key="shuffle",
            help="Off: ask them in the order the chapters list them")
        parsing = st.checkbox(
            "Also test parsing", value=True, key="parsing",
            help="Genitive and gender for nouns, principal parts for verbs, "
                 "the other genders for adjectives and pronouns")

    return {"files": files, "mode": mode, "count": int(count),
            "exhaustive": exhaustive, "shuffle": shuffle, "parsing": parsing}


# ---------------------------------------------------------------------------
# setup view
# ---------------------------------------------------------------------------

def setup_view(chapters: dict, opts: dict) -> None:
    st.title("Latin Vocab Quiz")
    st.caption("Drawn from the chapter notes in this vault.")

    pool = pool_for(chapters, opts["files"])
    total = len(pool)
    if not total:
        st.info("Pick at least one chapter in the sidebar.")
        return

    if opts["exhaustive"]:
        st.write(f"All **{total}** word{'' if total == 1 else 's'} will be asked.")
    elif opts["count"] > total:
        st.write(f"**{total}** words available — {opts['count']} questions "
                 "means some words will repeat.")
    else:
        st.write(f"**{total}** words available.")

    if st.button("Start quiz", type="primary"):
        questions = vocab.build_quiz(
            pool, opts["count"], opts["mode"], opts["parsing"],
            random.Random(), opts["exhaustive"], opts["shuffle"])
        begin_quiz(questions,
                   "Question sheet — every word" if opts["exhaustive"]
                   else "Question sheet",
                   opts["files"], opts["mode"], opts["parsing"])
        st.rerun()

    printable_section(pool, opts)


def printable_section(pool: list[vocab.Entry], opts: dict) -> None:
    with st.expander("Printable sheet"):
        st.caption("Chapters, mode, count, exhaustive, shuffle and parsing "
                   "come from the sidebar. Download the sheet, then print it "
                   "from your browser (or save it as a PDF).")
        c1, c2, c3 = st.columns(3)
        show_key = c1.checkbox("Answer key", value=True)
        twocol = c2.checkbox("Two columns")
        spacing = c3.selectbox("Line spacing", ["tight", "normal", "roomy"],
                               index=1)

        if st.button("Build sheet"):
            questions = vocab.build_quiz(
                pool, opts["count"], opts["mode"], opts["parsing"],
                random.Random(), opts["exhaustive"], opts["shuffle"])
            st.session_state.sheet = {
                "html": render_sheet(questions, sorted(opts["files"]),
                                     opts["mode"], opts["exhaustive"],
                                     show_key, spacing, twocol),
                "n": len(questions),
            }

        sheet = st.session_state.sheet
        if sheet:
            st.download_button(
                f"Download sheet ({sheet['n']} questions)",
                data=sheet["html"], file_name="latin-vocab-sheet.html",
                mime="text/html", type="primary")
            with st.expander("Preview"):
                html_component(sheet["html"], height=500, scrolling=True)
                st.caption("Printing from this preview would print the whole "
                           "page — download the file and print that.")


# ---------------------------------------------------------------------------
# quiz view
# ---------------------------------------------------------------------------

def question_block(q: dict) -> None:
    chips = (f'<span class="chip">{escape(q["pos"])}</span>'
             f'<span class="chip">{escape(q["source"].removesuffix(".md"))}</span>')
    st.markdown(
        f'<div class="qhead"><span class="qnum">{q["index"] + 1}.</span>'
        f'<span>{escape(q["prompt_label"])}</span>{chips}</div>'
        f'<div class="prompt{" latin" if q["direction"] == "la_to_en" else ""}">'
        f'{escape(q["prompt"])}</div>',
        unsafe_allow_html=True)

    st.text_input(
        "answer", key=f"ans_{q['index']}_main", label_visibility="collapsed",
        placeholder="English meaning…" if q["direction"] == "la_to_en"
        else "Latin word…")

    if q["fields"]:
        for col, f in zip(st.columns(len(q["fields"])), q["fields"]):
            col.text_input(f["label"], key=f"ans_{q['index']}_{f['key']}")


def quiz_view() -> None:
    questions = st.session_state.quiz
    st.title(st.session_state.quiz_title)

    # NB: the form key must not collide with a session_state key of our own.
    with st.form("quiz_form", border=False):
        for q in questions:
            question_block(q)
            st.divider()
        submitted = st.form_submit_button("Submit answers", type="primary")

    st.caption("Macrons are optional — you'll be told when you left one out.")
    if st.button("Start over"):
        st.session_state.view = "setup"
        st.rerun()

    if submitted:
        answers = [
            {
                "main": st.session_state.get(f"ans_{q['index']}_main", ""),
                "fields": {f["key"]: st.session_state.get(
                    f"ans_{q['index']}_{f['key']}", "") for f in q["fields"]},
            }
            for q in questions
        ]
        graded = vocab.grade(questions, answers)
        st.session_state.results = graded
        st.session_state.missed = graded["missed"]
        st.session_state.view = "results"
        st.rerun()


# ---------------------------------------------------------------------------
# results view
# ---------------------------------------------------------------------------

def row_html(label: str, given: str, answer: str, verdict: str) -> str:
    cls, mark, note = VERDICT[verdict]
    parts = [f'<div class="row {cls}"><span class="mark">{mark}</span>',
             '<div class="rowbody">',
             f'<span class="rowlabel">{escape(label)}</span>',
             '<div class="line"><span class="tag">you</span>'
             f'<span class="val">{escape(given) or "(blank)"}</span></div>']
    if verdict != "correct":
        parts.append('<div class="line right"><span class="tag">answer</span>'
                     f'<span class="val">{escape(answer)}</span></div>')
    if note:
        parts.append(f'<span class="note">{note}</span>')
    parts.append("</div></div>")
    return "".join(parts)


def result_html(r: dict) -> str:
    verdicts = [r["verdict"]] + [f["verdict"] for f in r["fields"]]
    worst = "bad" if "wrong" in verdicts else (
        "warn" if "macrons" in verdicts else "ok")
    rows = [row_html("meaning" if r["direction"] == "la_to_en" else "Latin",
                     r["given"], r["answer"], r["verdict"])]
    rows += [row_html(f["label"], f["given"], f["answer"], f["verdict"])
             for f in r["fields"]]
    return (
        f'<div class="result {worst}">'
        f'<div class="qhead"><span class="qnum">{r["index"] + 1}.</span>'
        f'<span>{escape(r["prompt_label"])}</span>'
        f'<span class="chip">{escape(r["pos"])}</span></div>'
        f'<div class="prompt{" latin" if r["direction"] == "la_to_en" else ""}">'
        f'{escape(r["prompt"])}</div>'
        f'{"".join(rows)}'
        f'<div class="fullentry">{escape(r["full_entry"])}</div></div>'
    )


def results_view(chapters: dict) -> None:
    graded = st.session_state.results
    s = graded["score"]
    st.title("Results")

    pct = round(s["main_correct"] / s["main_total"] * 100) if s["main_total"] else 0
    detail = f"{pct}% on vocabulary"
    if s["field_total"]:
        detail += f" · {s['field_correct']} / {s['field_total']} on parsing"
    st.markdown(
        f'<div class="bigscore">{s["main_correct"]} / {s["main_total"]}</div>'
        f'<div style="opacity:.7">{detail}</div>',
        unsafe_allow_html=True)
    st.write("")

    c1, c2 = st.columns([1, 2])
    if s["missed"]:
        if c1.button(f"Retest the {s['missed']} I missed", type="primary"):
            start_retest(chapters)
    else:
        c1.success("Nothing to retest.")
    if c2.button("New quiz"):
        st.session_state.view = "setup"
        st.rerun()

    st.divider()
    for r in graded["results"]:
        st.markdown(result_html(r), unsafe_allow_html=True)


def start_retest(chapters: dict) -> None:
    """Every word missed, asked the way round it was missed."""
    missed = st.session_state.missed
    pool = pool_for(chapters, st.session_state.quiz_files)
    by_key = {e.key: e for e in pool}
    # A chapter edited mid-session can drop a word; retest what is left.
    chosen = [by_key[m["key"]] for m in missed if m["key"] in by_key]
    if not chosen:
        st.warning("Those words are no longer in the chapter files.")
        return

    rng = random.Random()
    rng.shuffle(chosen)
    questions = vocab.make_questions(
        chosen, pool, st.session_state.quiz_mode, st.session_state.quiz_parsing,
        rng, {m["key"]: m["direction"] for m in missed})
    begin_quiz(questions, f"Retest — {len(questions)} missed",
               st.session_state.quiz_files, st.session_state.quiz_mode,
               st.session_state.quiz_parsing)
    st.rerun()


# ---------------------------------------------------------------------------

def main() -> None:
    init_state()
    if not VAULT.is_dir():
        st.error(f"No chapter folder at {VAULT}. Set $LATIN_VAULT to point at it.")
        return

    chapters = load_chapters(vault_stamp())
    if not chapters:
        st.error(f"No chapter markdown files found in {VAULT}.")
        return

    opts = sidebar(chapters)
    view = st.session_state.view
    if view == "quiz" and st.session_state.quiz:
        quiz_view()
    elif view == "results" and st.session_state.results:
        results_view(chapters)
    else:
        setup_view(chapters, opts)


main()
