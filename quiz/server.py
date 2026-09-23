#!/usr/bin/env python3
"""Local web server for the Latin vocab quiz.

Run it from anywhere:

    python quiz/server.py

then open http://localhost:8765 (it opens automatically).
Chapter markdown files are re-read on every request, so editing a chapter
and reloading the page is enough -- no restart needed.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import random
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import vocab

HERE = Path(__file__).resolve().parent
VAULT = HERE.parent
STATIC = HERE / "static"

QUIZZES: dict[str, list[dict]] = {}
QUIZ_LOCK = threading.Lock()
MAX_QUIZZES = 50


class Server(ThreadingHTTPServer):
    # Windows lets two sockets share a port when this is on, which silently
    # leaves a stale instance answering half the requests.
    allow_reuse_address = False
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = "LatinVocabQuiz/1.0"

    # ---------------- helpers ----------------

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def log_message(self, fmt, *args):        # quieter console
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    # ---------------- routing ----------------

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path == "/api/files":
            return self._json({"files": self._file_list()})

        if path in ("/", "/index.html"):
            path = "/index.html"

        target = (STATIC / path.lstrip("/")).resolve()
        if not str(target).startswith(str(STATIC)) or not target.is_file():
            return self._send(404, b"Not found", "text/plain; charset=utf-8")

        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype == "application/javascript":
            ctype += "; charset=utf-8"
        return self._send(200, target.read_bytes(), ctype)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/quiz":
                return self._start_quiz()
            if path == "/api/grade":
                return self._grade()
            if path == "/api/printable":
                return self._printable()
            if path == "/api/retest":
                return self._retest()
        except Exception as exc:                       # surface errors in the UI
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        return self._send(404, b"Not found", "text/plain; charset=utf-8")

    # ---------------- endpoints ----------------

    def _file_list(self):
        out = []
        for name, entries in vocab.load_vault(VAULT).items():
            by_pos: dict[str, int] = {}
            for e in entries:
                by_pos[e.pos] = by_pos.get(e.pos, 0) + 1
            out.append({"name": name, "count": len(entries), "by_pos": by_pos})
        return out

    def _options(self, req):
        """Shared sheet options: (pool, count, mode, parsing)."""
        wanted = req.get("files") or []
        count = max(1, min(int(req.get("count") or 10), 500))
        mode = req.get("mode", "mixed")
        if mode not in ("la_to_en", "en_to_la", "mixed"):
            mode = "mixed"
        include_parsing = bool(req.get("parsing", True))
        vault = vocab.load_vault(VAULT)
        pool = [e for name, entries in vault.items() if name in wanted
                for e in entries]
        return pool, count, mode, include_parsing

    def _remember(self, questions, files, mode, include_parsing) -> str:
        qid = uuid.uuid4().hex
        with QUIZ_LOCK:
            while len(QUIZZES) >= MAX_QUIZZES:
                QUIZZES.pop(next(iter(QUIZZES)), None)
            QUIZZES[qid] = {
                "questions": questions,
                "files": list(files),
                "mode": mode,
                "parsing": include_parsing,
                "missed": [],
            }
        return qid

    @staticmethod
    def _public(questions):
        """The quiz as the page sees it -- no answers until it is submitted."""
        return [
            {
                "index": q["index"],
                "direction": q["direction"],
                "prompt": q["prompt"],
                "prompt_label": q["prompt_label"],
                "pos": q["pos"],
                "source": q["source"],
                "fields": [{"key": f["key"], "label": f["label"]} for f in q["fields"]],
            }
            for q in questions
        ]

    def _start_quiz(self):
        req = self._body()
        pool, count, mode, include_parsing = self._options(req)
        if not pool:
            return self._json({"error": "No vocabulary found in the selected files."}, 400)

        exhaustive = bool(req.get("exhaustive"))
        shuffle = bool(req.get("shuffle", True))
        questions = vocab.build_quiz(pool, count, mode, include_parsing,
                                     random.Random(), exhaustive, shuffle)
        qid = self._remember(questions, req.get("files") or [], mode,
                             include_parsing)
        return self._json({"id": qid, "questions": self._public(questions),
                           "pool": len(pool), "exhaustive": exhaustive})

    def _retest(self):
        """Every word missed in a graded quiz, asked the same way round."""
        req = self._body()
        with QUIZ_LOCK:
            rec = QUIZZES.get(req.get("id"))
        if not rec:
            return self._json({"error": "That quiz expired -- please start a new one."}, 400)
        if not rec["missed"]:
            return self._json({"error": "Nothing to retest -- nothing was missed."}, 400)

        vault = vocab.load_vault(VAULT)
        pool = [e for name, entries in vault.items() if name in rec["files"]
                for e in entries]
        by_key = {e.key: e for e in pool}

        rng = random.Random()
        # A chapter edited mid-session can drop a word; retest what is left.
        chosen = [by_key[m["key"]] for m in rec["missed"] if m["key"] in by_key]
        directions = {m["key"]: m["direction"] for m in rec["missed"]}
        if not chosen:
            return self._json({"error": "Those words are no longer in the chapter files."}, 400)
        rng.shuffle(chosen)

        questions = vocab.make_questions(chosen, pool, rec["mode"],
                                         rec["parsing"], rng, directions)
        qid = self._remember(questions, rec["files"], rec["mode"],
                             rec["parsing"])
        return self._json({"id": qid, "questions": self._public(questions),
                           "pool": len(pool), "retest": True})

    def _printable(self):
        """A worksheet, answers included -- the print page needs the key."""
        req = self._body()
        pool, count, mode, include_parsing = self._options(req)
        if not pool:
            return self._json({"error": "No vocabulary found in the selected files."}, 400)

        exhaustive = bool(req.get("exhaustive"))
        shuffle = bool(req.get("shuffle", True))
        questions = vocab.build_quiz(pool, count, mode, include_parsing,
                                     random.Random(), exhaustive, shuffle)
        sheet = [
            {
                "index": q["index"],
                "direction": q["direction"],
                "prompt": q["prompt"],
                "pos": q["pos"],
                "source": q["source"],
                "answer": q["answer"],
                "full_entry": q["full_entry"],
                "fields": [{"label": f["label"], "short": f["short"],
                            "answer": f["answer"]} for f in q["fields"]],
            }
            for q in questions
        ]
        return self._json({
            "questions": sheet,
            "files": sorted({q["source"] for q in questions}),
            "pool": len(pool),
            "exhaustive": exhaustive,
            "mode": mode,
        })

    def _grade(self):
        req = self._body()
        qid = req.get("id")
        with QUIZ_LOCK:
            rec = QUIZZES.get(qid)
        if not rec:
            return self._json({"error": "That quiz expired -- please start a new one."}, 400)

        graded = vocab.grade(rec["questions"], req.get("answers") or [])
        with QUIZ_LOCK:
            if qid in QUIZZES:                 # remember what to retest
                QUIZZES[qid]["missed"] = graded["missed"]
        graded.pop("missed", None)             # the page only needs the count
        return self._json(graded)


def main():
    global VAULT

    ap = argparse.ArgumentParser(description="Latin vocab quiz server")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--vault", type=Path, default=VAULT,
                    help="folder to read chapter markdown from "
                         "(default: the folder containing quiz/)")
    args = ap.parse_args()
    VAULT = args.vault.resolve()

    port = args.port
    for attempt in range(20):
        try:
            httpd = Server(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    else:
        raise SystemExit("Could not find a free port.")

    url = f"http://localhost:{port}/"
    print(f"Latin vocab quiz -> {url}")
    print(f"Reading chapters from: {VAULT}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
