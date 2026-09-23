'use strict';

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

const params = new URLSearchParams(location.search);
const config = {
  files: params.getAll('file'),
  count: parseInt(params.get('count'), 10) || 10,
  mode: params.get('mode') || 'mixed',
  parsing: params.get('parsing') !== '0',
  exhaustive: params.get('exhaustive') === '1',
  shuffle: params.get('shuffle') !== '0',
};

const MODE_LABEL = {
  la_to_en: 'Latin → English',
  en_to_la: 'English → Latin',
  mixed: 'Mixed',
};

/* ------------------------------- rendering ------------------------------ */

function blank(width) {
  const b = el('span', 'blank');
  if (width) b.style.flexBasis = width;
  return b;
}

function questionBlock(q) {
  const item = el('li', 'pq');

  const line = el('div', 'pqline');
  line.append(el('span', q.direction === 'la_to_en' ? 'pword latin' : 'pword',
                 q.prompt));
  line.append(blank());
  line.append(el('span', 'ppos', q.pos));
  item.append(line);

  if (q.fields.length) {
    const grid = el('div', 'pfields');
    for (const f of q.fields) {
      const cell = el('div', 'pfield');
      cell.append(el('span', 'pflabel', f.short || f.label));
      cell.append(blank());
      grid.append(cell);
    }
    item.append(grid);
  }
  return item;
}

function keyBlock(questions) {
  const wrap = el('section', 'answerkey');
  wrap.append(el('h2', null, 'Answer key'));
  const ol = el('ol', 'keylist');
  for (const q of questions) {
    const li = el('li', 'keyitem');
    li.append(el('span', 'keyprompt', q.prompt));
    li.append(el('span', 'keysep', '—'));
    li.append(el('span', 'keyanswer', q.answer));
    if (q.fields.length) {
      li.append(el('span', 'keyfields',
                   ` (${q.fields.map((f) => f.answer).join(', ')})`));
    }
    ol.append(li);
  }
  wrap.append(ol);
  return wrap;
}

function render(data) {
  const sheet = $('#sheet');
  sheet.textContent = '';

  const chapters = data.files.map((f) => f.replace(/\.md$/, '')).join(', ');
  const head = el('header', 'sheethead');
  head.append(el('h1', null, 'Latin Vocabulary'));
  const meta = el('p', 'sheetmeta');
  meta.append(el('span', null, chapters || 'no chapters'));
  meta.append(el('span', null, `${data.questions.length} questions`));
  meta.append(el('span', null, MODE_LABEL[data.mode] || data.mode));
  if (data.exhaustive) meta.append(el('span', 'stamp', 'complete list'));
  head.append(meta);
  head.append(el('p', 'namedate', 'Name ______________________     Date __________'));
  sheet.append(head);

  const ol = el('ol', 'plist');
  data.questions.forEach((q) => ol.append(questionBlock(q)));
  sheet.append(ol);

  if (data.questions.length) sheet.append(keyBlock(data.questions));
  applyView();
}

/* -------------------------------- options ------------------------------- */

function applyView() {
  document.body.dataset.spacing = $('#spacing').value;
  document.body.classList.toggle('twocol', $('#twocol').checked);
  document.body.classList.toggle('nokey', !$('#show-key').checked);
}

async function load() {
  const r = await fetch('/api/printable', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  const data = await r.json();
  if (data.error) {
    $('#sheet').textContent = '';
    $('#sheet').append(el('p', 'loading', data.error));
    return;
  }
  render(data);
  document.title = `Latin Vocab — ${data.questions.length} questions`;
}

if (params.get('key') === '0') $('#show-key').checked = false;
// A full chapter list is long -- start such sheets in two columns.
if (config.exhaustive && !config.parsing) $('#twocol').checked = true;

$('#do-print').addEventListener('click', () => window.print());
$('#reroll').addEventListener('click', load);
$('#show-key').addEventListener('change', applyView);
$('#twocol').addEventListener('change', applyView);
$('#spacing').addEventListener('change', applyView);

load();
