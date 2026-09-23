"""Build a standalone printable worksheet as a single HTML file.

No Streamlit, no server: the returned string is a complete document with its
CSS and the three view toggles inlined, so it prints properly from wherever it
is downloaded to.
"""

from __future__ import annotations

from html import escape

MODE_LABEL = {
    "la_to_en": "Latin → English",
    "en_to_la": "English → Latin",
    "mixed": "Mixed",
}

CSS = """
* { box-sizing: border-box; }

body {
  margin: 0;
  padding: 0 1rem 3rem;
  background: #f2f0eb;
  color: #000;
  font: 12pt/1.45 "Iowan Old Style", "Palatino Linotype", Georgia, serif;
}

.toolbar {
  position: sticky; top: 0; z-index: 5;
  display: flex; flex-wrap: wrap; align-items: center; gap: 0.9rem;
  max-width: 48rem; margin: 0 auto; padding: 0.7rem 0;
  background: #f2f0eb; border-bottom: 1px solid #d8d3c8; font-size: 0.85rem;
}
.toolbar label { display: flex; align-items: center; gap: 0.35rem; }
.toolbar select, .toolbar button { font: inherit; }
button.print {
  font-weight: 600; background: #7a2e2e; color: #fff; border: 0;
  border-radius: 7px; padding: 0.4rem 0.9rem; cursor: pointer;
}

#sheet {
  max-width: 48rem; margin: 1.5rem auto; padding: 2.2rem 2.4rem 2.8rem;
  background: #fff; border: 1px solid #d8d3c8;
}

.sheethead { margin-bottom: 1.6rem; }
.sheethead h1 { margin: 0; font-size: 1.5rem; letter-spacing: -0.01em; }
.sheetmeta {
  display: flex; flex-wrap: wrap; gap: 0.9rem; margin: 0.3rem 0 0;
  font-size: 0.82rem; color: #4a463f;
}
.sheetmeta .stamp {
  border: 1px solid #4a463f; border-radius: 3px; padding: 0 0.35rem;
  text-transform: uppercase; letter-spacing: 0.05em; font-size: 0.72rem;
}
.namedate {
  margin: 1.1rem 0 0; font-size: 0.9rem;
  border-top: 1px solid #000; padding-top: 0.8rem;
}

.plist { margin: 0; padding-left: 2.1rem; }
.pq { margin-bottom: 0.55rem; break-inside: avoid; }
body[data-spacing=tight] .pq { margin-bottom: 0.15rem; }
body[data-spacing=roomy] .pq { margin-bottom: 1.2rem; }

.pqline { display: flex; align-items: baseline; gap: 0.5rem; }
.pword { white-space: nowrap; }
.pword.latin { font-style: italic; }
.ppos {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em;
  color: #6b655c; white-space: nowrap;
}

.blank {
  flex: 1 1 4rem; min-width: 3rem; border-bottom: 1px solid #000;
  align-self: flex-end; height: 1.05em;
}
body[data-spacing=roomy] .blank { height: 1.5em; }

.pfields {
  display: flex; flex-wrap: wrap; gap: 0.4rem 1.4rem;
  margin: 0.15rem 0 0; font-size: 0.85rem;
}
.pfield {
  display: flex; align-items: baseline; gap: 0.4rem;
  flex: 1 1 11rem; min-width: 9rem;
}
.pflabel { color: #4a463f; white-space: nowrap; }

body.twocol .plist { columns: 2; column-gap: 2.2rem; }

.answerkey { margin-top: 2.4rem; break-before: page; }
.answerkey h2 {
  margin: 0 0 0.7rem; font-size: 1rem; text-transform: uppercase;
  letter-spacing: 0.08em; border-bottom: 1px solid #000; padding-bottom: 0.3rem;
}
.keylist {
  margin: 0; padding-left: 2.1rem; columns: 2; column-gap: 2.2rem;
  font-size: 0.85rem;
}
.keyitem { break-inside: avoid; margin-bottom: 0.15rem; }
.keyprompt { font-style: italic; }
.keysep { color: #6b655c; margin: 0 0.25rem; }
.keyanswer { font-weight: 600; }
.keyfields { color: #4a463f; }

body.nokey .answerkey { display: none; }

@page { margin: 0.7in 0.75in; }

@media print {
  body { background: #fff; padding: 0; font-size: 11pt; }
  .toolbar { display: none; }
  #sheet { max-width: none; margin: 0; padding: 0; border: 0; }
  .sheethead h1 { font-size: 1.3rem; }
}
"""

SCRIPT = """
const body = document.body;
document.getElementById('do-print').addEventListener('click', () => window.print());
document.getElementById('show-key').addEventListener('change', (e) => {
  body.classList.toggle('nokey', !e.target.checked);
});
document.getElementById('twocol').addEventListener('change', (e) => {
  body.classList.toggle('twocol', e.target.checked);
});
document.getElementById('spacing').addEventListener('change', (e) => {
  body.dataset.spacing = e.target.value;
});
"""


def _question_html(q: dict) -> str:
    word_cls = "pword latin" if q["direction"] == "la_to_en" else "pword"
    out = ['<li class="pq">', '<div class="pqline">',
           f'<span class="{word_cls}">{escape(q["prompt"])}</span>',
           '<span class="blank"></span>',
           f'<span class="ppos">{escape(q["pos"])}</span>',
           '</div>']
    if q["fields"]:
        out.append('<div class="pfields">')
        for f in q["fields"]:
            label = escape(f.get("short") or f["label"])
            out.append('<div class="pfield">'
                       f'<span class="pflabel">{label}</span>'
                       '<span class="blank"></span></div>')
        out.append("</div>")
    out.append("</li>")
    return "".join(out)


def _key_html(questions: list[dict]) -> str:
    out = ['<section class="answerkey"><h2>Answer key</h2><ol class="keylist">']
    for q in questions:
        extra = ""
        if q["fields"]:
            joined = ", ".join(f["answer"] for f in q["fields"])
            extra = f'<span class="keyfields"> ({escape(joined)})</span>'
        out.append('<li class="keyitem">'
                   f'<span class="keyprompt">{escape(q["prompt"])}</span>'
                   '<span class="keysep">—</span>'
                   f'<span class="keyanswer">{escape(q["answer"])}</span>'
                   f'{extra}</li>')
    out.append("</ol></section>")
    return "".join(out)


def render_sheet(questions: list[dict], files: list[str], mode: str,
                 exhaustive: bool = False, show_key: bool = True,
                 spacing: str = "normal", twocol: bool = False) -> str:
    """A complete HTML document for the given questions."""
    chapters = ", ".join(f.removesuffix(".md") for f in files) or "no chapters"
    classes = " ".join(c for c in ("twocol" if twocol else "",
                                   "" if show_key else "nokey") if c)
    stamp = '<span class="stamp">complete list</span>' if exhaustive else ""

    body = [
        '<article id="sheet">',
        '<header class="sheethead"><h1>Latin Vocabulary</h1>',
        '<p class="sheetmeta">',
        f"<span>{escape(chapters)}</span>",
        f"<span>{len(questions)} questions</span>",
        f"<span>{escape(MODE_LABEL.get(mode, mode))}</span>",
        stamp,
        "</p>",
        '<p class="namedate">Name ______________________'
        "&nbsp;&nbsp;&nbsp;&nbsp; Date __________</p>",
        "</header>",
        '<ol class="plist">',
        *(_question_html(q) for q in questions),
        "</ol>",
    ]
    if questions:
        body.append(_key_html(questions))
    body.append("</article>")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Latin Vocab — {len(questions)} questions</title>
<style>{CSS}</style>
</head>
<body class="{classes}" data-spacing="{escape(spacing)}">
<div class="toolbar">
  <button type="button" id="do-print" class="print">Print</button>
  <label><input type="checkbox" id="show-key"{" checked" if show_key else ""}>
    answer key</label>
  <label>lines
    <select id="spacing">
      {"".join(f'<option value="{s}"{" selected" if s == spacing else ""}>{s}</option>'
               for s in ("tight", "normal", "roomy"))}
    </select>
  </label>
  <label><input type="checkbox" id="twocol"{" checked" if twocol else ""}>
    two columns</label>
</div>
{"".join(body)}
<script>{SCRIPT}</script>
</body>
</html>
"""
