"""Google account controls, reliable saves and the test-history dashboard."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import uuid
from zoneinfo import ZoneInfo

import streamlit as st

from account_history import HistoryError, google_identity, practice_record, recent_summary
from firestore_history import FirestoreHistory
import quiz_record


LABELS = {"vocabulary": "Vocabulary", "morphology": "Declension & conjugation"}


@dataclass
class AccountContext:
    identity: object = None
    store: object = None
    login_ready: bool = False
    error: str = ""


def current_identity():
    return google_identity(st.user.to_dict())


def _settings():
    try:
        return st.secrets.to_dict()
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return {}


def _present(value):
    return isinstance(value, str) and bool(value) and not value.startswith("REPLACE_")


@st.cache_resource(show_spinner=False)
def _client(project, database, service_account_json):
    from google.cloud import firestore
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_info(json.loads(service_account_json))
    return firestore.Client(project=project, database=database, credentials=credentials)


def context():
    settings = _settings()
    auth = settings.get("auth", {})
    google = auth.get("google", {})
    login_ready = (all(_present(auth.get(key)) for key in ("redirect_uri", "cookie_secret"))
                   and all(_present(google.get(key)) for key in ("client_id", "client_secret"))
                   and google.get("server_metadata_url") == "https://accounts.google.com/.well-known/openid-configuration")
    identity_error = ""
    try:
        identity = current_identity()
    except HistoryError as exc:
        identity = None
        identity_error = str(exc)
    owner = identity.uid if identity else None
    if "_account_owner" in st.session_state and st.session_state["_account_owner"] != owner:
        # Identity changes must not carry drafts, history caches or queued writes
        # from another account. Normal st.login/st.logout already start sessions.
        st.session_state.clear()
    st.session_state["_account_owner"] = owner
    result = AccountContext(identity=identity, login_ready=login_ready, error=identity_error)
    if not identity:
        return result
    config = settings.get("firestore", {})
    service_account = config.get("service_account", {})
    if not _present(config.get("project_id")) or not all(
            _present(service_account.get(key)) for key in ("project_id", "client_email", "private_key", "token_uri")):
        result.error = "Account history is not configured yet. You can still practice and download test records."
        return result
    if service_account["project_id"] != config["project_id"]:
        result.error = "The account database configuration needs to be checked by the app owner."
        return result
    try:
        client = _client(config["project_id"], config.get("database_id", "(default)"),
                         json.dumps(service_account, sort_keys=True))
        result.store = FirestoreHistory(client, identity.uid)
    except Exception:
        # SDK/configuration exceptions can contain credential details.
        result.error = "Account history could not connect. The app owner needs to check its configuration."
    return result


def sidebar(account):
    next_page = st.session_state.pop("_account_next_page", None)
    if next_page:
        st.session_state["account_page"] = next_page
    st.session_state.setdefault("account_page", "Practice")
    with st.sidebar:
        st.radio("Page", ("Practice", "Account"), key="account_page")
        if st.session_state.get("view") == "quiz" or st.session_state.get("morph_view") == "quiz":
            st.caption("Submit answers before switching pages to keep your current responses.")
        if account.identity:
            st.caption(account.identity.email or account.identity.name)
            st.button("Sign out", key="account_logout", on_click=st.logout)
        else:
            st.button("Sign in with Google", key="account_login", disabled=not account.login_ready,
                      on_click=st.login, args=("google",),
                      help="Sign in before starting a test to save it to your account.")
            if not account.login_ready:
                st.caption("Account sign-in is awaiting setup. Practice is available.")
        if account.error:
            st.warning(account.error)


def begin_attempt(kind, source_ids=()):
    try:
        identity = current_identity()
    except HistoryError:
        identity = None
    st.session_state[f"_account_attempt_{kind}"] = {
        "id": uuid.uuid4().hex, "owner": identity.uid if identity else None,
        "source_ids": list(source_ids), "saved": False}


def completed(kind, record, questions, graded):
    try:
        identity = current_identity()
    except HistoryError:
        return
    if not identity:
        return
    key = f"_account_attempt_{kind}"
    if key not in st.session_state:
        begin_attempt(kind)
    attempt = st.session_state[key]
    if attempt["owner"] != identity.uid:
        return
    if record["version"] != quiz_record.REFERENCE_VERSION:
        record = quiz_record.make_record(kind, record["configuration"], questions, record["retest"], compact=True)
        record = quiz_record.with_result(record, questions, graded)
    pending = st.session_state.setdefault("_account_pending_saves", {})
    pending.setdefault(attempt["id"], {"owner": identity.uid, "kind": kind, "record": record,
                                      "completed_at": datetime.now(timezone.utc),
                                      "source_ids": attempt["source_ids"], "attempted": False, "error": ""})


def _retry(attempt_id=None):
    for key, pending in st.session_state.get("_account_pending_saves", {}).items():
        if attempt_id is None or key == attempt_id:
            pending["attempted"] = False


def flush_pending(account):
    if not account.identity or account.store is None:
        return
    pending = st.session_state.get("_account_pending_saves", {})
    for attempt_id, item in list(pending.items()):
        if item["owner"] != account.identity.uid or item["attempted"]:
            continue
        item["attempted"] = True
        try:
            account.store.save(attempt_id, item["record"], item["completed_at"], item["source_ids"])
        except HistoryError as exc:
            item["error"] = str(exc)
        except Exception:
            item["error"] = "Your test could not be saved. Retry when the connection is available."
        else:
            del pending[attempt_id]
            attempt = st.session_state.get(f"_account_attempt_{item['kind']}", {})
            if attempt.get("id") == attempt_id:
                attempt["saved"] = True
            st.session_state.pop("_account_history", None)
            st.session_state.pop("_account_detail", None)


def save_status(kind):
    attempt = st.session_state.get(f"_account_attempt_{kind}", {})
    if not attempt.get("owner"):
        st.caption("Sign in with Google before starting a test to save future scores.")
    elif attempt.get("saved"):
        st.caption("Saved to your account.")
    else:
        pending = st.session_state.get("_account_pending_saves", {}).get(attempt.get("id"))
        if pending:
            st.warning(pending["error"] or "This result is waiting to be saved to your account.")
            st.button("Retry saving this test", key=f"account_retry_{kind}",
                      on_click=_retry, args=(attempt["id"],))


def preserve_practice_state():
    """Keep saved widget settings from being cleaned up on the Account page."""
    settings = {"files", "count", "mode", "parsing", "exhaustive", "shuffle", "retest_selection",
                "morph_kinds", "morph_voices", "morph_tenses", "morph_moods", "morph_gender",
                "morph_retest_selection"}
    for key in list(st.session_state):
        if key in settings or key.startswith(("ans_", "unfamiliar_", "morph_ans_", "morph_unfamiliar_")):
            st.session_state[key] = st.session_state[key]


def _date(value):
    return value.astimezone(ZoneInfo("America/Chicago")).strftime("%b %d, %Y · %I:%M %p %Z")


def _score(attempt):
    score = attempt["score"]
    prefix = "main" if attempt["kind"] == "vocabulary" else "entry"
    unit = "vocabulary answers" if attempt["kind"] == "vocabulary" else "entries"
    text = f"{score[prefix + '_correct']} / {score[prefix + '_total']} {unit}"
    if score["field_total"]:
        text += f" · {score['field_correct']} / {score['field_total']} fields"
    return text


def _queue_practice(records, selection, source_ids, vault):
    record = practice_record(records, selection)
    quiz_record.reconstruct(record, vault)  # Validate before replacing either active test.
    st.session_state["pending_record"] = record
    st.session_state["_account_pending_source_ids"] = list(source_ids)
    st.session_state["_account_next_page"] = "Practice"
    st.rerun()


def _detail(account, attempt_id, vault):
    if st.button("Back to history", key="account_back"):
        st.session_state.pop("_account_detail_id", None)
        st.rerun()
    cached = st.session_state.get("_account_detail")
    if not cached or cached["attempt_id"] != attempt_id:
        cached = account.store.get(attempt_id)
        st.session_state["_account_detail"] = cached
    record = cached["record"]
    st.subheader(LABELS[cached["kind"]])
    st.write(_date(cached["completed_at"]))
    st.write(_score(cached))
    st.caption("Chapters: " + ", ".join(cached["files"]))
    all_entries, wrong_entries = st.columns(2)
    if all_entries.button("Retest every entry", key="account_retest_all", type="primary"):
        _queue_practice([record], "all", [attempt_id], vault)
    if wrong_entries.button("Retest wrong entries", key="account_retest_wrong", disabled=not cached["wrong_count"]):
        _queue_practice([record], "wrong", [attempt_id], vault)
    questions = quiz_record.reconstruct(record, vault)
    wrong = record["result"]["wrong"]
    only_wrong = st.checkbox("Show incorrect entries only", value=True, key=f"account_wrong_only_{attempt_id}")
    rows = []
    for question in questions:
        fields = wrong.get(str(question["index"]), [])
        if only_wrong and not fields:
            continue
        labels = {field["key"]: field["label"] for field in question["fields"]}
        labels["main"] = "Vocabulary answer"
        rows.append({"Question": question["index"] + 1, "Entry": question["prompt"],
                     "Test": question["prompt_label"], "Result": "Incorrect" if fields else "Correct",
                     "Incorrect fields": ", ".join(labels[field] for field in fields)})
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.success("No incorrect entries in this test.")
    st.download_button("Download saved test record", quiz_record.dumps(record),
                       file_name=f"latin-{record['kind']}-{attempt_id}.json", mime="application/json",
                       key="account_record_download", on_click="ignore")


def dashboard(account, vault):
    st.title("Your account")
    if not account.identity:
        st.info("Sign in with Google to save scores, review your history, and practice recent mistakes.")
        return
    st.write(f"Welcome, {account.identity.name}.")
    if account.store is None:
        st.info("Your history will be available once account setup is complete.")
        return
    pending = st.session_state.get("_account_pending_saves", {})
    if pending:
        st.warning(f"{len(pending)} test(s) have not been saved yet. Retry before leaving this session.")
        st.button("Retry unsaved tests", key="account_retry_all", on_click=_retry)
    try:
        detail_id = st.session_state.get("_account_detail_id")
        if detail_id:
            _detail(account, detail_id, vault)
            return
        if st.button("Refresh history", key="account_refresh"):
            st.session_state.pop("_account_history", None)
        history = st.session_state.get("_account_history")
        if history is None:
            page = account.store.list_page()
            history = {"attempts": page.attempts, "cursor": page.cursor, "visible": 20}
            st.session_state["_account_history"] = history
        rows = history["attempts"]
        if not rows:
            st.info("No saved tests yet. Start a practice test while signed in; submitting it saves your score.")
            return
        count = st.selectbox("Recent tests", [5, 10, 20, 50], index=1, key="account_recent_count")
        recent = rows[:count]
        summary = recent_summary(recent)
        st.subheader(f"Your latest {len(recent)} tests")
        tests, vocabulary, morphology = st.columns(3)
        tests.metric("Tests completed", summary["tests"])
        for column, label, prefix in ((vocabulary, "Vocabulary accuracy", "vocabulary"),
                                       (morphology, "Morphology cell accuracy", "morphology")):
            total = summary[f"{prefix}_total"]
            column.metric(label, f"{summary[f'{prefix}_correct'] / total:.0%}" if total else "—")
        st.caption(f"{summary['entries']} entries tested · {summary['wrong']} incorrect entries across these tests.")
        for column, kind in zip(st.columns(2), LABELS):
            relevant = [row for row in recent if row["kind"] == kind and row["wrong_count"]]
            label = "Practice recent vocabulary mistakes" if kind == "vocabulary" else "Practice recent morphology mistakes"
            if column.button(label, key=f"account_recent_{kind}", disabled=not relevant):
                saved = account.store.get_many([row["attempt_id"] for row in relevant])
                _queue_practice([row["record"] for row in saved], "wrong",
                                [row["attempt_id"] for row in saved], vault)
        st.caption("Recent mistake practice includes anything missed in this window, even if answered correctly later. "
                   "Repeated questions with the same settings are included once.")
        st.subheader("Test history")
        for row in rows[:history["visible"]]:
            with st.container(border=True):
                description, action = st.columns([4, 1])
                description.write(f"**{LABELS[row['kind']]}** · {_date(row['completed_at'])}")
                description.caption(_score(row) + (" · Retest" if row["retest"] else ""))
                if action.button("View test", key=f"account_open_{row['attempt_id']}"):
                    st.session_state["_account_detail_id"] = row["attempt_id"]
                    st.rerun()
        if history["visible"] < len(rows) or history["cursor"] is not None:
            if st.button("Load older tests", key="account_older"):
                if history["visible"] + 20 > len(rows) and history["cursor"] is not None:
                    page = account.store.list_page(cursor=history["cursor"])
                    history["attempts"].extend(page.attempts)
                    history["cursor"] = page.cursor
                history["visible"] += 20
                st.rerun()
    except (HistoryError, ValueError) as exc:
        st.error(str(exc))
    except Exception:
        st.error("Your history could not be loaded. Please try refreshing it shortly.")
