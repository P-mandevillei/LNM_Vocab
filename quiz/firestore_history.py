"""Server-only Firestore access, always bound to one authenticated owner."""

from dataclasses import dataclass

from account_history import HistoryError, attempt_document, decode_record, valid_id


SUMMARY_FIELDS = ("schema_version", "owner_id", "attempt_id", "completed_at", "kind", "retest",
                  "entry_count", "wrong_count", "score", "files", "source_attempt_ids")


@dataclass
class HistoryPage:
    attempts: list
    cursor: object = None


class FirestoreHistory:
    def __init__(self, client, owner):
        if not valid_id(owner, 64):
            raise HistoryError("Please sign in before opening your history.")
        self.client = client
        self.owner = owner
        self.collection = client.collection("latin_accounts").document(owner).collection("attempts")

    def _document(self, attempt_id):
        if not valid_id(attempt_id):
            raise HistoryError("That saved test could not be found.")
        return self.collection.document(attempt_id)

    def _read(self, snapshot, include_record=False):
        if not snapshot.exists:
            raise HistoryError("That saved test could not be found.")
        document = snapshot.to_dict()
        if document.get("owner_id") != self.owner or document.get("attempt_id") != snapshot.id:
            raise HistoryError("That saved test could not be accessed.")
        if document.get("schema_version") != 1 or any(key not in document for key in SUMMARY_FIELDS):
            raise HistoryError("That saved test has an unsupported format.")
        summary = {key: document[key] for key in SUMMARY_FIELDS}
        if include_record:
            record = decode_record(document.get("payload"), document.get("payload_sha256"))
            if record["kind"] != summary["kind"] or record["result"]["score"] != summary["score"]:
                raise HistoryError("That saved test has inconsistent results.")
            summary["record"] = record
        return summary

    def save(self, attempt_id, record, completed_at, source_ids=()):
        from google.api_core.exceptions import AlreadyExists

        document = attempt_document(self.owner, attempt_id, record, completed_at, source_ids)
        reference = self._document(attempt_id)
        try:
            reference.create(document, retry=None, timeout=8)
        except AlreadyExists:
            # A retry after an uncertain network response must not duplicate or
            # overwrite a submitted attempt, or change its completion timestamp.
            existing = reference.get(retry=None, timeout=8)
            self._read(existing)
            if existing.to_dict().get("payload_sha256") != document["payload_sha256"]:
                raise HistoryError("A different result already exists for this test. Start a new attempt.")

    def list_page(self, limit=50, cursor=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise HistoryError("Choose a history page size between 1 and 100.")
        query = self.collection.select(SUMMARY_FIELDS).order_by("completed_at", direction="DESCENDING")
        if cursor is not None:
            query = query.start_after(cursor)
        snapshots = list(query.limit(limit + 1).stream(retry=None, timeout=8))
        rows = [self._read(snapshot) for snapshot in snapshots[:limit]]
        return HistoryPage(rows, snapshots[limit - 1] if len(snapshots) > limit else None)

    def get(self, attempt_id):
        return self._read(self._document(attempt_id).get(retry=None, timeout=8), include_record=True)

    def get_many(self, attempt_ids):
        ids = list(dict.fromkeys(attempt_ids))
        if len(ids) > 50:
            raise HistoryError("Choose at most 50 recent tests.")
        if not ids:
            return []
        snapshots = self.client.get_all([self._document(attempt_id) for attempt_id in ids], retry=None, timeout=8)
        rows = {snapshot.id: self._read(snapshot, include_record=True) for snapshot in snapshots}
        if set(rows) != set(ids):
            raise HistoryError("Some recent tests could not be found. Refresh your history and try again.")
        return [rows[attempt_id] for attempt_id in ids]
