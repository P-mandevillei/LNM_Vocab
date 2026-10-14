"""Streamlit UI for the same morphology engine used by server.py.

Morphology sessions and answer widgets have separate keys from vocabulary.
Quiz/retest answer snapshots remain valid when chapters or overrides change.
"""

from html import escape
from pathlib import Path

import streamlit as st

import morphology as m
import quiz_record
import streamlit_records as records


KIND_LABELS = {
    "noun": "Noun declension",
    "adjective": "Adjective declension in a given gender",
    "verb": "Verb conjugation and infinitive",
    "pair": "Noun + agreeing adjective",
}
GENDER_LABELS = {"mixed": "Any given gender", "m": "Masculine", "f": "Feminine", "n": "Neuter"}
VERDICTS = {"correct": ("ok", "✓"), "macrons": ("warn", "≈"), "wrong": ("bad", "✗")}

CSS = """
<style>
.morph-results { width:100%; border-collapse:collapse; margin:.6rem 0 1rem; }
.morph-results th, .morph-results td { text-align:left; vertical-align:top;
  padding:.4rem; border-bottom:1px solid rgba(128,128,128,.3); }
.morph-results th:first-child { width:22%; }
.morph-results td { width:39%; overflow-wrap:anywhere; }
.morph-cell.ok { background:rgba(31,122,77,.13); }
.morph-cell.warn { background:rgba(160,106,18,.15); }
.morph-cell.bad { background:rgba(163,38,38,.13); }
.morph-cell { padding:.3rem; border-radius:5px; }
.morph-correction { display:block; font-weight:600; margin-top:.2rem; }
.morph-source { display:block; font-size:.85em; margin-top:.2rem; }
.morph-sources { margin-top:.3rem; }
.morph-sources summary { cursor:pointer; font-size:.85em; opacity:.75; }
</style>
"""


def init_state():
    for key, value in {"morph_view": "setup", "morph_quiz": None,
                       "morph_title": "Declension & conjugation",
                       "morph_results": None, "morph_missed": []}.items():
        st.session_state.setdefault(key, value)


def begin_quiz(questions, opts, title="Declension & conjugation", retest=False):
    for key in [key for key in st.session_state if key.startswith(("morph_ans_", "morph_unfamiliar_"))]:
        del st.session_state[key]
    st.session_state.update(morph_view="quiz", morph_quiz=questions,
                            morph_title=title, morph_results=None, morph_missed=[],
                            morph_record=quiz_record.make_record("morphology", opts, questions, retest))


def settings(shared):
    # Keep these widgets mounted during quizzes/results so their preferences
    # survive Streamlit's widget cleanup and switching between the two tabs.
    with st.expander("Morphology settings", expanded=st.session_state.morph_view == "setup"):
        st.caption("Chapters, number of questions, Exhaustive and Shuffle order come from the sidebar. "
                   "Vocabulary Mode and Also test parsing apply only to the Vocabulary tab.")
        kinds = st.multiselect("Entry types", list(m.KINDS), default=list(m.KINDS),
                               format_func=KIND_LABELS.get, key="morph_kinds")
        voices = st.multiselect("Verb voices", list(m.VOICES), default=list(m.VOICES),
                               format_func=str.title, key="morph_voices", disabled="verb" not in kinds)
        tenses = st.multiselect("Verb tenses", list(m.TENSES), default=["present"],
                               format_func=lambda s: s.replace("_", " ").title(),
                               key="morph_tenses", disabled="verb" not in kinds)
        moods = st.multiselect("Verb moods", list(m.MOODS), default=["indicative"],
                              format_func=str.title, key="morph_moods", disabled="verb" not in kinds)
        gender = st.selectbox("Adjectives alone", list(GENDER_LABELS), format_func=GENDER_LABELS.get,
                              key="morph_gender", disabled="adjective" not in kinds)
        st.caption("Each verb gets one supported combination from your selections. "
                   "Unavailable combinations are skipped; unavailable persons are disabled. "
                   "The infinitive has the same voice: perfect for perfect-system tenses, present otherwise. "
                   "In pairs the adjective agrees with the noun's gender, case and number.")
    return {**shared, "kinds": kinds, "voices": voices, "tenses": tenses, "moods": moods, "gender": gender}


def setup_view(chapters, req, vault):
    pool = [entry for name, entries in chapters.items() if name in req["files"] for entry in entries]
    if not pool:
        st.info("Pick at least one chapter in the sidebar.")
        return
    if not req["kinds"]:
        st.info("Select at least one entry type.")
        return
    try:
        opts = m.options(req)
        lexicon = m.load_lexicon(vault, include_cache=False)
        sources = m.table_sources(vault)
        available, excluded, counts = m.candidates(pool, opts, lexicon=lexicon, sources=sources)
    except ValueError as exc:
        st.error(str(exc))
        return

    total = len(available)
    if opts["exhaustive"]:
        st.write(f"All **{total}** eligible entries will be asked.")
    else:
        st.write(f"**{total}** entries available." +
                 (" Some entries will repeat." if total and opts["count"] > total else ""))
    st.caption(" · ".join(f"{counts[kind]} {KIND_LABELS[kind].lower()}"
                          for kind in m.KINDS if counts[kind]))
    st.caption("Declensions cover all six cases in singular and plural; unavailable forms are disabled. "
               "Exhaustive pairs cover every eligible noun and adjective, reusing the shorter list.")
    if excluded:
        with st.expander(f"{len(excluded)} unavailable chapter entries"):
            for entry in excluded:
                st.write(f"{entry['word']} ({entry['source']}): {entry['reason']}")
    if not total:
        st.info("No supported entries match these settings. Pairs need both nouns and adjectives.")
    if st.button("Start morphology quiz", key="morph_start", type="primary", disabled=not total):
        data = m.build_quiz(pool, opts, lexicon=lexicon, sources=sources)
        begin_quiz(data["questions"], {"files": req["files"], **opts})
        st.rerun()


def table_rows(question):
    fields = {field["key"]: field for field in question["fields"]}
    for index, label in enumerate(question["rows"]):
        prefix = f"p{index + 1}" if question["kind"] == "verb" else label.lower()
        yield label, [fields[f"{prefix}_{number}"] for number in m.NUMBERS]


def heading(question):
    st.markdown(
        f'<div class="qhead"><span class="qnum">{question["index"] + 1}.</span>'
        f'<span>{escape(question["prompt_label"])}</span>'
        f'<span class="chip">{escape(question["source"].removesuffix(".md"))}</span></div>'
        f'<div class="prompt latin">{escape(question["prompt"])}</div>',
        unsafe_allow_html=True)
    for note in question["notes"]:
        st.caption(note)


def answer_input(question, field):
    st.text_input(f"Entry {question['index'] + 1}: {field['label']}",
                  key=f"morph_ans_{question['index']}_{field['key']}",
                  label_visibility="collapsed", disabled=field["disabled"],
                  placeholder="—" if field["disabled"] else "")


def question_block(question):
    heading(question)
    for col, title in zip(st.columns([1.2, 2, 2]),
                          ["Person" if question["kind"] == "verb" else "Case", *question["columns"]]):
        col.markdown(f"**{title}**")
    for label, fields in table_rows(question):
        label_col, singular, plural = st.columns([1.2, 2, 2])
        label_col.write(label)
        with singular:
            answer_input(question, fields[0])
        with plural:
            answer_input(question, fields[1])
    if question["kind"] == "verb":
        field = next(f for f in question["fields"] if f["key"] == "infinitive")
        st.write(field["label"])
        answer_input(question, field)
    st.checkbox("Unfamiliar", key=f"morph_unfamiliar_{question['index']}",
                help="Keep this entry at the top of the answers page.")


def quiz_view():
    questions = st.session_state.morph_quiz
    st.subheader(st.session_state.morph_title)
    records.download(st.session_state.morph_record, "morph_record_download")
    with st.form("morph_quiz_form", border=False):
        for question in questions:
            question_block(question)
            st.divider()
        submitted = st.form_submit_button("Submit morphology answers", type="primary")
    st.caption("Macrons are optional. Every available cell is graded; retesting repeats whole missed entries.")
    if st.button("Start over", key="morph_start_over"):
        st.session_state.morph_view = "setup"
        st.rerun()
    if submitted:
        answers = [{"unfamiliar": st.session_state.get(f"morph_unfamiliar_{question['index']}", False),
                    "fields": {field["key"]: st.session_state.get(
            f"morph_ans_{question['index']}_{field['key']}", "") for field in question["fields"]}}
                   for question in questions]
        graded = m.grade(questions, answers)
        st.session_state.update(morph_results=graded, morph_missed=graded["missed"], morph_view="results")
        st.rerun()


def result_cell(field):
    if field["disabled"]:
        return '<span aria-label="Unavailable">—</span>'
    cls, mark = VERDICTS[field["verdict"]]
    given = escape(field["given"]) or "(blank)"
    correction = f'<span class="morph-correction">Answer: {escape(field["answer"])}</span>'
    note = '<span class="note">macrons missing / wrong</span>' if field["verdict"] == "macrons" else ""
    if field.get("disagreement"):
        note += '<span class="morph-correction">⚠ Rule and importer spellings differ.</span>'
    sources = "".join(f'<span class="morph-source">{escape(name.title())}: {escape(" / ".join(forms))}</span>'
                      for name, forms in field.get("answer_sources", {}).items())
    if sources:
        precedence = '<span class="note">Chapter form takes precedence.</span>' if field.get("chapter_precedence") else ""
        sources = (f'<details class="morph-sources"><summary>Answer sources</summary>'
                   f'{precedence}{sources}</details>')
    return f'<div class="morph-cell {cls}">{mark} {given}{correction}{note}{sources}</div>'


def result_table(question):
    first = "Person" if question["kind"] == "verb" else "Case"
    out = ['<table class="morph-results"><thead><tr>',
           f'<th scope="col">{first}</th>',
           *(f'<th scope="col">{escape(title)}</th>' for title in question["columns"]),
           '</tr></thead><tbody>']
    for label, fields in table_rows(question):
        out.append(f'<tr><th scope="row">{escape(label)}</th>')
        out.extend(f'<td>{result_cell(field)}</td>' for field in fields)
        out.append('</tr>')
    if question["kind"] == "verb":
        field = next(f for f in question["fields"] if f["key"] == "infinitive")
        out.append(f'<tr><th scope="row">{escape(field["label"])}</th>'
                   f'<td colspan="2">{result_cell(field)}</td></tr>')
    out.append('</tbody></table>')
    return "".join(out)


def results_view():
    graded = st.session_state.morph_results
    score = graded["score"]
    st.subheader("Morphology results")
    st.markdown(f'**{score["entry_correct"]} / {score["entry_total"]} entries correct** · '
                f'{score["field_correct"]} / {score["field_total"]} cells correct')
    counts = quiz_record.retest_counts("morphology", st.session_state.morph_quiz, graded["results"])
    selection = st.selectbox("Retest entries", list(quiz_record.RETEST_CHOICES),
                             format_func=lambda key: f"{quiz_record.RETEST_CHOICES[key]} ({counts[key]})",
                             key="morph_retest_selection")
    retest, new = st.columns([1, 2])
    if counts[selection]:
        label = f"Retest the {counts[selection]} I missed" if selection == "wrong" else f"Retest {counts[selection]} {'entry' if counts[selection] == 1 else 'entries'}"
        if retest.button(label, key="morph_retest", type="primary"):
            indices = quiz_record.retest_indices("morphology", st.session_state.morph_quiz, graded["results"], selection)
            questions = m.retest(st.session_state.morph_quiz, indices)
            opts = {**st.session_state.morph_record["configuration"], "count": min(len(questions), 500),
                    "exhaustive": False, "retest_selection": selection}
            begin_quiz(questions, opts, f"Retest — {len(questions)} {'entry' if len(questions) == 1 else 'entries'}", retest=True)
            st.rerun()
    else:
        retest.info("Nothing to retest for this selection.")
    if new.button("New quiz", key="morph_new"):
        st.session_state.morph_view = "setup"
        st.rerun()
    st.divider()
    records.download(st.session_state.morph_record, "morph_record_download")
    def render_result(question):
        heading(question)
        st.markdown(result_table(question), unsafe_allow_html=True)
        st.caption(question["full_entry"])
        st.divider()
    records.results_groups(graded["results"], render_result)


def render(chapters: dict, shared: dict, vault: Path):
    init_state()
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("Declension & conjugation")
    req = settings(shared)
    if st.session_state.morph_view == "quiz" and st.session_state.morph_quiz:
        quiz_view()
    elif st.session_state.morph_view == "results" and st.session_state.morph_results:
        results_view()
    else:
        setup_view(chapters, req, vault)
