'use strict';

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

const STORE = 'latin-quiz-prefs';
let files = [];
let quiz = null;

/* ------------------------------ preferences ----------------------------- */

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch { return {}; }
}
function savePrefs() {
  const prefs = {
    files: selectedFiles(),
    mode: $('input[name=mode]:checked').value,
    count: $('#count').value,
    parsing: $('#parsing').checked,
    exhaustive: $('#exhaustive').checked,
    shuffle: $('#shuffle').checked,
    answerkey: $('#answerkey').checked,
  };
  localStorage.setItem(STORE, JSON.stringify(prefs));
}

/* -------------------------------- setup --------------------------------- */

function selectedFiles() {
  return [...document.querySelectorAll('#filelist input:checked')].map((c) => c.value);
}

function updatePool() {
  const chosen = new Set(selectedFiles());
  const total = files.filter((f) => chosen.has(f.name))
                     .reduce((s, f) => s + f.count, 0);
  const count = parseInt($('#count').value, 10) || 0;
  const exhaustive = $('#exhaustive').checked;
  let msg;
  if (!total) {
    msg = 'No chapters selected.';
  } else if (exhaustive) {
    msg = `All ${total} word${total === 1 ? '' : 's'} will be asked.`;
  } else {
    msg = `${total} word${total === 1 ? '' : 's'} available`;
    msg += count > total ? ` — ${count} questions means some words will repeat.` : '.';
  }
  $('#poolinfo').textContent = msg;
  $('#count').disabled = exhaustive;
}

function renderFiles() {
  const box = $('#filelist');
  box.textContent = '';
  if (!files.length) {
    box.append(el('p', 'hint', 'No markdown files with vocabulary found in the vault.'));
    return;
  }
  const prefs = loadPrefs();
  const previously = prefs.files;
  for (const f of files) {
    const label = el('label', 'fileitem');
    const cb = el('input');
    cb.type = 'checkbox';
    cb.value = f.name;
    cb.checked = previously ? previously.includes(f.name) : true;
    cb.addEventListener('change', () => { updatePool(); savePrefs(); });

    const breakdown = Object.entries(f.by_pos)
      .map(([pos, n]) => `${n} ${pos}${n === 1 ? '' : 's'}`)
      .join(', ');

    label.append(cb, el('span', 'fname', f.name),
                 el('span', 'fmeta', breakdown || `${f.count} entries`));
    box.append(label);
  }
  updatePool();
}

async function fetchFiles() {
  const r = await fetch('/api/files');
  files = (await r.json()).files;
  renderFiles();
}

/* --------------------------------- quiz --------------------------------- */

function questionCard(q) {
  const card = el('div', 'question');
  const head = el('div', 'qhead');
  head.append(el('span', 'qnum', `${q.index + 1}.`));
  head.append(el('span', 'qlabel', q.prompt_label));
  head.append(el('span', 'chip', q.pos));
  head.append(el('span', 'chip subtle', q.source.replace(/\.md$/, '')));
  card.append(head);

  card.append(el('div', q.direction === 'la_to_en' ? 'prompt latin' : 'prompt', q.prompt));

  const main = el('input', 'answer');
  main.type = 'text';
  main.autocomplete = 'off';
  main.spellcheck = false;
  main.dataset.index = q.index;
  main.dataset.role = 'main';
  main.placeholder = q.direction === 'la_to_en' ? 'English meaning…' : 'Latin word…';
  card.append(main);

  if (q.fields.length) {
    const grid = el('div', 'fields');
    for (const f of q.fields) {
      const wrap = el('label', 'field');
      wrap.append(el('span', 'flabel', f.label));
      const inp = el('input', 'answer small');
      inp.type = 'text';
      inp.autocomplete = 'off';
      inp.spellcheck = false;
      inp.dataset.index = q.index;
      inp.dataset.role = 'field';
      inp.dataset.key = f.key;
      wrap.append(inp);
      grid.append(wrap);
    }
    card.append(grid);
  }
  return card;
}

function showQuiz(data, title) {
  quiz = data;
  const form = $('#quizform');
  form.textContent = '';
  data.questions.forEach((q) => form.append(questionCard(q)));

  $('#quiz-title').textContent = title;
  $('#setup').hidden = true;
  $('#results').hidden = true;
  $('#quiz').hidden = false;
  window.scrollTo({ top: 0 });
  form.querySelector('input')?.focus();
}

async function post(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return r.json();
}

async function startQuiz() {
  const err = $('#setup-error');
  err.hidden = true;

  const data = await post('/api/quiz', {
    files: selectedFiles(),
    count: parseInt($('#count').value, 10) || 10,
    mode: $('input[name=mode]:checked').value,
    parsing: $('#parsing').checked,
    exhaustive: $('#exhaustive').checked,
    shuffle: $('#shuffle').checked,
  });
  if (data.error) {
    err.textContent = data.error;
    err.hidden = false;
    return;
  }
  showQuiz(data, data.exhaustive ? 'Question sheet — every word' : 'Question sheet');
}

async function startRetest() {
  const data = await post('/api/retest', { id: quiz.id });
  if (data.error) {
    alert(data.error);
    return;
  }
  showQuiz(data, `Retest — ${data.questions.length} missed`);
}

/* ------------------------------- grading -------------------------------- */

function collectAnswers() {
  const answers = quiz.questions.map(() => ({ main: '', fields: {} }));
  for (const inp of document.querySelectorAll('#quizform input.answer')) {
    const i = parseInt(inp.dataset.index, 10);
    if (inp.dataset.role === 'main') answers[i].main = inp.value;
    else answers[i].fields[inp.dataset.key] = inp.value;
  }
  return answers;
}

const VERDICT = {
  correct: { cls: 'ok', mark: '✓', note: '' },
  macrons: { cls: 'warn', mark: '≈', note: 'macrons missing / wrong' },
  wrong: { cls: 'bad', mark: '✗', note: '' },
};

function row(label, given, answer, verdict) {
  const v = VERDICT[verdict];
  const r = el('div', `row ${v.cls}`);
  r.append(el('span', 'mark', v.mark));
  const body = el('div', 'rowbody');
  body.append(el('span', 'rowlabel', label));
  const yours = el('div', 'yours');
  yours.append(el('span', 'tag', 'you'));
  yours.append(el('span', 'val', given || '(blank)'));
  body.append(yours);
  if (verdict !== 'correct') {
    const right = el('div', 'right');
    right.append(el('span', 'tag', 'answer'));
    right.append(el('span', 'val', answer));
    body.append(right);
  }
  if (v.note) body.append(el('span', 'note', v.note));
  r.append(body);
  return r;
}

function renderResults(data) {
  const s = data.score;
  const scoreBox = $('#score');
  scoreBox.textContent = '';
  const pct = Math.round((s.main_correct / s.main_total) * 100);
  scoreBox.append(el('div', 'bigscore', `${s.main_correct} / ${s.main_total}`));
  const detail = `${pct}% on vocabulary` +
    (s.field_total ? ` · ${s.field_correct} / ${s.field_total} on parsing` : '');
  scoreBox.append(el('div', 'hint', detail));

  // Macron slips are shown but don't count as mistakes worth retesting.
  const retest = $('#retest');
  retest.hidden = !s.missed;
  if (s.missed) {
    retest.textContent = `Retest the ${s.missed} I missed`;
  } else {
    scoreBox.append(el('div', 'hint', 'Nothing to retest.'));
  }

  const list = $('#resultlist');
  list.textContent = '';
  for (const r of data.results) {
    const worst = r.verdict === 'wrong' || r.fields.some((f) => f.verdict === 'wrong')
      ? 'bad' : (r.verdict === 'macrons' || r.fields.some((f) => f.verdict === 'macrons')
      ? 'warn' : 'ok');
    const card = el('div', `question result ${worst}`);
    const head = el('div', 'qhead');
    head.append(el('span', 'qnum', `${r.index + 1}.`));
    head.append(el('span', 'qlabel', r.prompt_label));
    head.append(el('span', 'chip', r.pos));
    card.append(head);
    card.append(el('div', r.direction === 'la_to_en' ? 'prompt latin' : 'prompt', r.prompt));
    card.append(row(r.direction === 'la_to_en' ? 'meaning' : 'Latin',
                    r.given, r.answer, r.verdict));
    for (const f of r.fields) card.append(row(f.label, f.given, f.answer, f.verdict));
    card.append(el('div', 'fullentry', r.full_entry));
    list.append(card);
  }

  $('#quiz').hidden = true;
  $('#results').hidden = false;
  window.scrollTo({ top: 0 });
}

async function submitQuiz() {
  const data = await post('/api/grade', { id: quiz.id, answers: collectAnswers() });
  if (data.error) {
    alert(data.error);
    return;
  }
  renderResults(data);
}

/* -------------------------------- wiring -------------------------------- */

function backToSetup() {
  $('#quiz').hidden = true;
  $('#results').hidden = true;
  $('#setup').hidden = false;
  fetchFiles();
  window.scrollTo({ top: 0 });
}

function openPrintSheet() {
  const chosen = selectedFiles();
  const err = $('#setup-error');
  if (!chosen.length) {
    err.textContent = 'Pick at least one chapter first.';
    err.hidden = false;
    return;
  }
  err.hidden = true;

  const p = new URLSearchParams();
  chosen.forEach((f) => p.append('file', f));
  p.set('count', parseInt($('#count').value, 10) || 10);
  p.set('mode', $('input[name=mode]:checked').value);
  p.set('parsing', $('#parsing').checked ? '1' : '0');
  p.set('exhaustive', $('#exhaustive').checked ? '1' : '0');
  p.set('shuffle', $('#shuffle').checked ? '1' : '0');
  p.set('key', $('#answerkey').checked ? '1' : '0');
  window.open(`/print.html?${p}`, '_blank');
}

$('#start').addEventListener('click', () => { savePrefs(); startQuiz(); });
$('#print').addEventListener('click', () => { savePrefs(); openPrintSheet(); });
$('#submit').addEventListener('click', submitQuiz);
$('#retest').addEventListener('click', startRetest);
$('#abandon').addEventListener('click', backToSetup);
$('#again').addEventListener('click', backToSetup);
$('#reload-files').addEventListener('click', fetchFiles);
$('#select-all').addEventListener('click', () => {
  document.querySelectorAll('#filelist input').forEach((c) => (c.checked = true));
  updatePool(); savePrefs();
});
$('#select-none').addEventListener('click', () => {
  document.querySelectorAll('#filelist input').forEach((c) => (c.checked = false));
  updatePool(); savePrefs();
});
$('#count').addEventListener('input', () => { updatePool(); savePrefs(); });
$('#parsing').addEventListener('change', savePrefs);
$('#exhaustive').addEventListener('change', () => { updatePool(); savePrefs(); });
$('#shuffle').addEventListener('change', savePrefs);
$('#answerkey').addEventListener('change', savePrefs);
document.querySelectorAll('input[name=mode]').forEach((r) =>
  r.addEventListener('change', savePrefs));

// Enter moves to the next box; Ctrl+Enter submits the sheet.
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || $('#quiz').hidden) return;
  e.preventDefault();
  if (e.ctrlKey || e.metaKey) { submitQuiz(); return; }
  const inputs = [...document.querySelectorAll('#quizform input.answer')];
  const i = inputs.indexOf(document.activeElement);
  if (i >= 0 && i < inputs.length - 1) inputs[i + 1].focus();
  else if (i === inputs.length - 1) submitQuiz();
});

(function init() {
  const prefs = loadPrefs();
  if (prefs.count) $('#count').value = prefs.count;
  if (prefs.parsing !== undefined) $('#parsing').checked = prefs.parsing;
  if (prefs.exhaustive !== undefined) $('#exhaustive').checked = prefs.exhaustive;
  if (prefs.shuffle !== undefined) $('#shuffle').checked = prefs.shuffle;
  if (prefs.answerkey !== undefined) $('#answerkey').checked = prefs.answerkey;
  if (prefs.mode) {
    const r = document.querySelector(`input[name=mode][value="${prefs.mode}"]`);
    if (r) r.checked = true;
  }
  fetchFiles();
})();
