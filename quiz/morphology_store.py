"""Compile imported morphology data for indexed, read-only quiz access."""

from contextlib import closing
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zlib

from morphology_cache import (CacheError, TableCatalog, TableEntry, decode_cache,
                              replace_cache_file, summarize_record)


STORE_VERSION = 2
ACQUISITION_TABLE = """CREATE TABLE IF NOT EXISTS acquisition (
    id INTEGER PRIMARY KEY CHECK (id = 1), content BLOB NOT NULL)"""


def _open_readonly(path):
    return sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)


def _snapshot(db):
    if db.execute("PRAGMA user_version").fetchone()[0] != STORE_VERSION:
        raise CacheError("Unsupported morphology SQLite schema. Recompile the cache.")
    row = db.execute("SELECT digest, size FROM snapshot").fetchone()
    if row is None:
        raise CacheError("Morphology SQLite snapshot metadata is missing. Recompile the cache.")
    return row


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def read_acquisition(path):
    try:
        with closing(_open_readonly(Path(path).resolve())) as db:
            row = db.execute("SELECT content FROM acquisition WHERE id = 1").fetchone()
        if row is not None:
            return zlib.decompress(row[0])
    except (sqlite3.Error, zlib.error) as exc:
        raise CacheError(f"Could not read morphology acquisition data: {exc}") from exc
    raise CacheError("Morphology acquisition data is missing.")


def write_acquisition(path, content):
    """Checkpoint imports while the app continues using the published tables."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    compressed = zlib.compress(content)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(ACQUISITION_TABLE)
        row = db.execute("SELECT content FROM acquisition WHERE id = 1").fetchone()
        if row == (compressed,):
            return False
        db.execute("INSERT OR REPLACE INTO acquisition VALUES (1, ?)", (compressed,))
    return True


def compile_store(source):
    """Publish the acquisition state, catalog and answer tables together."""
    source = Path(source).resolve()
    path = source.with_suffix(".sqlite3")
    source_stat = source.stat()
    content = read_acquisition(source) if source.suffix == ".sqlite3" else source.read_bytes()
    snapshot = (hashlib.sha256(content).hexdigest(), len(content))
    if path.exists():
        try:
            with closing(_open_readonly(path)) as db:
                if _snapshot(db) == snapshot and db.execute("PRAGMA quick_check").fetchone() == ("ok",):
                    return path
        except (CacheError, sqlite3.Error):
            pass
    data = decode_cache(content, source)

    fd, temporary_name = tempfile.mkstemp(dir=path.parent, suffix=".sqlite3.tmp")
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.executescript(f"""
                PRAGMA user_version = {STORE_VERSION};
                CREATE TABLE snapshot (digest TEXT NOT NULL, size INTEGER NOT NULL);
                CREATE TABLE catalog (id TEXT PRIMARY KEY, request TEXT NOT NULL,
                    configurations TEXT NOT NULL, passive_forms INTEGER NOT NULL) WITHOUT ROWID;
                CREATE TABLE bindings (key TEXT PRIMARY KEY, id TEXT NOT NULL) WITHOUT ROWID;
                CREATE TABLE payloads (id TEXT PRIMARY KEY, data BLOB NOT NULL) WITHOUT ROWID;
            """)
            db.execute("INSERT INTO snapshot VALUES (?, ?)", snapshot)
            db.execute(ACQUISITION_TABLE)
            db.execute("INSERT INTO acquisition VALUES (1, ?)", (zlib.compress(content),))
            db.executemany("INSERT INTO bindings VALUES (?, ?)",
                           ((key, value["entry"]) for key, value in sorted(data["bindings"].items())))
            for key, record in sorted(data["entries"].items()):
                if record["status"] != "ready":
                    continue
                entry = summarize_record(key, record)
                db.execute("INSERT INTO catalog VALUES (?, ?, ?, ?)",
                           (key, _json(entry.request), _json(sorted(entry.configurations)), entry.passive_forms))
                cells = {name: {"forms": cell["forms"]} for name, cell in record["candidate"]["cells"].items()}
                payload = zlib.compress(_json({"candidate": {"cells": cells}}).encode("utf-8"))
                db.execute("INSERT INTO payloads VALUES (?, ?)", (key, payload))
        current = source.stat()
        if (current.st_mtime_ns, current.st_size) != (source_stat.st_mtime_ns, source_stat.st_size):
            raise CacheError("The acquisition cache changed during compilation. Recompile the cache.")
        replace_cache_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


class SQLiteTableSources(TableCatalog):
    def __init__(self, path, snapshot, records, bindings):
        self.path = path
        self.snapshot = snapshot
        super().__init__(records, bindings)

    def load_records(self, record_ids):
        keys = sorted(record_ids)
        records = {}
        try:
            with closing(_open_readonly(self.path)) as db:
                db.execute("BEGIN")
                if _snapshot(db) != self.snapshot:
                    raise CacheError("The morphology cache was refreshed. Start the quiz again.")
                for start in range(0, len(keys), 500):
                    batch = keys[start:start + 500]
                    placeholders = ",".join("?" for _ in batch)
                    for key, payload in db.execute(f"SELECT id, data FROM payloads WHERE id IN ({placeholders})", batch):
                        records[key] = json.loads(zlib.decompress(payload))
        except CacheError:
            raise
        except (sqlite3.Error, ValueError, zlib.error) as exc:
            raise CacheError(f"Could not read morphology answer tables: {exc}") from exc
        if records.keys() != set(keys):
            raise CacheError("Morphology answer tables are missing. Recompile the cache.")
        return records


def sqlite_sources(path, source):
    stat = path.stat()
    stamp = None
    if source is not None:
        try:
            source_stat = source.stat()
            stamp = (source_stat.st_size, source_stat.st_mtime_ns)
        except FileNotFoundError:
            pass
    return _sqlite_sources(str(path.resolve()), stat.st_size, stat.st_mtime_ns, source, stamp)


@lru_cache(maxsize=8)
def _sqlite_sources(path, size, modified, source, stamp):
    try:
        with closing(_open_readonly(path)) as db:
            db.execute("BEGIN")
            snapshot = _snapshot(db)
            if stamp is not None:
                if stamp[0] != snapshot[1]:
                    return None
                # Checkout/copy order can give an unchanged JSON a newer mtime.
                if stamp[1] > modified:
                    digest = hashlib.sha256()
                    with Path(source).open("rb") as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(block)
                    if digest.hexdigest() != snapshot[0]:
                        return None
            records = {key: TableEntry(key, json.loads(req), frozenset(map(tuple, json.loads(configs))), bool(passive))
                       for key, req, configs, passive in db.execute("SELECT * FROM catalog")}
            bindings = dict(db.execute("SELECT key, id FROM bindings"))
    except CacheError:
        raise
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise CacheError(f"Could not read morphology catalog: {exc}") from exc
    return SQLiteTableSources(path, snapshot, records, bindings)
