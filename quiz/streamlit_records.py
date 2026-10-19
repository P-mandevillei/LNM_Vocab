"""Record upload/download UI shared by the two Streamlit testers."""

import streamlit as st

import quiz_record
import streamlit_accounts as accounts


def upload_changed():
    uploaded = st.session_state.get("record_upload")
    if uploaded is None:
        return
    try:
        st.session_state.pending_record = quiz_record.loads(uploaded.getvalue())
        st.session_state.pop("record_error", None)
    except ValueError as exc:
        st.session_state.record_error = str(exc)


def restore_pending(vault):
    pending = st.session_state.pop("pending_record", None)
    if pending is None:
        return
    source_ids = st.session_state.pop("_account_pending_source_ids", [])
    # Validate before changing any existing quiz or widget preference.
    try:
        record = quiz_record.validate(pending)
        questions = quiz_record.reconstruct(record, vault)
    except ValueError as exc:
        st.session_state.record_error = str(exc)
        return
    kind, opts = record["kind"], record["configuration"]
    for key in ("files", "count", "exhaustive", "shuffle"):
        st.session_state[key] = opts[key]
    prefix = "morph_" if kind == "morphology" else ""
    answer_prefix = "morph_ans_" if prefix else "ans_"
    unfamiliar_prefix = "morph_unfamiliar_" if prefix else "unfamiliar_"
    for key in list(st.session_state):
        if key.startswith((answer_prefix, unfamiliar_prefix)):
            del st.session_state[key]
    if kind == "morphology":
        for key in ("kinds", "voices", "tenses", "moods", "gender"):
            st.session_state[f"morph_{key}"] = opts[key]
    else:
        for key in ("mode", "parsing"):
            st.session_state[key] = opts[key]
        st.session_state.update(quiz_files=opts["files"], quiz_mode=opts["mode"],
                                quiz_parsing=opts["parsing"])
    title = "Recorded retest" if record["retest"] else "Recorded test"
    # An upload starts a new attempt; completed results stay in the downloaded
    # record and must not be attached to its new blank responses.
    record.pop("result", None)
    st.session_state.update({f"{prefix}view": "quiz", f"{prefix}quiz": questions,
                             f"{prefix}{'title' if prefix else 'quiz_title'}": title,
                             f"{prefix}results": None, f"{prefix}missed": [],
                             f"{prefix}record": record,
                             f"{prefix}retest_selection": opts.get("retest_selection", "wrong")})
    st.session_state.record_notice = ("Declension & conjugation" if prefix else "Vocabulary")
    st.session_state["_practice_tab"] = st.session_state.record_notice
    accounts.begin_attempt(kind, source_ids)


def upload_section():
    with st.sidebar.expander("Test records"):
        st.file_uploader("Upload test record", type=["json"], key="record_upload",
                         on_change=upload_changed,
                         help="Rebuild the recorded questions from the installed chapter files.")
        st.caption("Compact records require their original chapters. Answers and unfamiliar marks start blank.")
        if st.session_state.get("record_error"):
            st.error(st.session_state.record_error)
        if st.session_state.get("record_notice"):
            st.success(f"Record restored in the {st.session_state.record_notice} tab.")


def download(record, key):
    st.download_button("Download test record", data=quiz_record.dumps(record),
                       file_name=f"latin-{record['kind']}-{'retest' if record['retest'] else 'test'}-record.json",
                       mime="application/json", key=key, on_click="ignore")


def results_groups(results, render):
    unfamiliar, remaining = quiz_record.review_groups(
        results, [r["index"] for r in results if r.get("unfamiliar")])
    if unfamiliar:
        st.subheader(f"Unfamiliar entries ({len(unfamiliar)})")
        for result in unfamiliar:
            render(result)
    else:
        st.caption("No entries marked unfamiliar.")
    if remaining:
        with st.expander(f"Remaining entries ({len(remaining)}) — wrong answers first", expanded=False):
            for result in remaining:
                render(result)
