'use strict';

(() => {
  const $ = (selector) => document.querySelector(selector);
  const node = (tag, cls, text) => {
    const item = document.createElement(tag);
    if (cls) item.className = cls;
    if (text !== undefined) item.textContent = text;
    return item;
  };
  const STORE = 'latin-morphology-prefs';
  const labels = { noun: 'noun', adjective: 'adjective', verb: 'verb', pair: 'noun + adjective' };
  const verdicts = {
    correct: { cls: 'ok', mark: '✓' },
    macrons: { cls: 'warn', mark: '≈' },
    wrong: { cls: 'bad', mark: '✗' },
  };
  let quiz = null;
  let poolRevision = 0;
  let submitting = false;

  function prefs(key = STORE) {
    try { return JSON.parse(localStorage.getItem(key)) || {}; } catch { return {}; }
  }

  function settings() {
    return {
      files: [...document.querySelectorAll('#m-files input:checked')].map((c) => c.value),
      kinds: [...document.querySelectorAll('#m-kinds input:checked')].map((c) => c.value),
      voice: $('#m-voice').value,
      gender: $('#m-gender').value,
      count: parseInt($('#m-count').value, 10) || 10,
      exhaustive: $('#m-exhaustive').checked,
      shuffle: $('#m-shuffle').checked,
    };
  }

  function save() {
    try { localStorage.setItem(STORE, JSON.stringify(settings())); } catch { /* preferences are optional */ }
  }

  function error(target, message = '') {
    const box = $(target);
    box.textContent = message;
    box.hidden = !message;
  }

  async function request(url, body) {
    const response = await fetch(url, body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || 'The request failed.');
    return data;
  }

  async function refreshPool() {
    const revision = ++poolRevision;
    const opts = settings();
    $('#m-count').disabled = opts.exhaustive;
    $('#m-voice').disabled = !opts.kinds.includes('verb');
    $('#m-gender').disabled = !opts.kinds.includes('adjective');
    $('#m-start').disabled = true;
    $('#m-pool').textContent = 'Checking available entries…';
    $('#m-exclusions').hidden = true;
    error('#m-setup-error');
    if (!opts.files.length || !opts.kinds.length) {
      $('#m-pool').textContent = !opts.files.length ? 'No chapters selected.' : 'Select at least one entry type.';
      return;
    }
    try {
      const data = await request('/api/morphology/pool', opts);
      if (revision !== poolRevision) return;
      const breakdown = Object.entries(data.counts).filter(([, n]) => n)
        .map(([kind, n]) => `${n} ${labels[kind]}`).join(', ');
      const message = opts.exhaustive ? `All ${data.pool} eligible entries will be asked.`
        : `${data.pool} entries available${opts.count > data.pool && data.pool ? ' — some entries will repeat.' : '.'}`;
      $('#m-pool').textContent = message + (breakdown ? ` ${breakdown}.` : ' Pairs require both nouns and adjectives.');
      $('#m-start').disabled = !data.pool;
      const list = $('#m-exclusion-list');
      list.textContent = '';
      if (data.excluded.length) {
        $('#m-exclusion-title').textContent = `${data.excluded.length} unavailable chapter entries`;
        for (const entry of data.excluded) {
          list.append(node('li', '', `${entry.word} (${entry.source}): ${entry.reason}`));
        }
        $('#m-exclusions').hidden = false;
      }
    } catch (exc) {
      if (revision !== poolRevision) return;
      $('#m-pool').textContent = '';
      error('#m-setup-error', exc.message);
    }
  }

  async function loadFiles() {
    try {
      const data = await request('/api/morphology/files');
      const previous = prefs().files || prefs('latin-quiz-prefs').files;
      const list = $('#m-files');
      list.textContent = '';
      for (const file of data.files) {
        const label = node('label', 'fileitem');
        const checkbox = node('input');
        checkbox.type = 'checkbox';
        checkbox.value = file.name;
        checkbox.checked = previous ? previous.includes(file.name) : true;
        checkbox.addEventListener('change', () => { save(); refreshPool(); });
        const breakdown = Object.entries(file.by_pos).map(([kind, n]) => `${n} ${kind}${n === 1 ? '' : 's'}`).join(', ');
        label.append(checkbox, node('span', 'fname', file.name), node('span', 'fmeta', breakdown));
        list.append(label);
      }
      if (!data.files.length) list.append(node('p', 'hint', 'No chapter files found.'));
      await refreshPool();
    } catch (exc) {
      $('#m-start').disabled = true;
      error('#m-setup-error', exc.message);
    }
  }

  function showView(view) {
    for (const name of ['setup', 'quiz', 'results']) $(`#m-${name}`).hidden = name !== view;
    window.scrollTo({ top: 0 });
  }

  function input(q, field) {
    const answer = node('input', 'answer');
    answer.type = 'text';
    answer.autocomplete = 'off';
    answer.spellcheck = false;
    answer.dataset.index = q.index;
    answer.dataset.key = field.key;
    answer.setAttribute('aria-label', `Entry ${q.index + 1}, ${q.prompt}, ${field.label}`);
    answer.disabled = field.disabled;
    if (field.disabled) answer.placeholder = '—';
    return answer;
  }

  function resultCell(field) {
    if (field.disabled) return node('span', 'm-na', '—');
    const verdict = verdicts[field.verdict];
    const cell = node('div', `m-cell ${verdict.cls}`);
    cell.append(node('span', 'mark', verdict.mark), node('span', '', field.given || '(blank)'));
    if (field.verdict !== 'correct') {
      cell.append(node('span', 'm-correction', field.answer));
      if (field.verdict === 'macrons') cell.append(node('span', 'note', 'macrons missing / wrong'));
    }
    cell.setAttribute('aria-label', `${field.label}: ${field.verdict}. You: ${field.given || 'blank'}. Answer: ${field.answer}`);
    return cell;
  }

  function table(q, review) {
    const wrap = node('div', 'm-table-wrap');
    const grid = node('table', 'm-table');
    const thead = node('thead');
    const header = node('tr');
    header.append(node('th', '', q.kind === 'verb' ? 'Person' : 'Case'));
    for (const title of q.columns) {
      const th = node('th', '', title);
      th.scope = 'col';
      header.append(th);
    }
    thead.append(header);
    grid.append(thead);
    const tbody = node('tbody');
    const fields = Object.fromEntries(q.fields.map((field) => [field.key, field]));
    q.rows.forEach((label, rowIndex) => {
      const tr = node('tr');
      const th = node('th', '', label);
      th.scope = 'row';
      tr.append(th);
      for (const number of ['singular', 'plural']) {
        const key = `${q.kind === 'verb' ? `p${rowIndex + 1}` : label.toLowerCase()}_${number}`;
        const td = node('td');
        td.append(review ? resultCell(fields[key]) : input(q, fields[key]));
        tr.append(td);
      }
      tbody.append(tr);
    });
    grid.append(tbody);
    wrap.append(grid);
    return wrap;
  }

  function card(q, review = false) {
    const cls = review ? `question result ${verdicts[q.verdict].cls}` : 'question';
    const item = node('div', cls);
    const head = node('div', 'qhead');
    head.append(node('span', 'qnum', `${q.index + 1}.`), node('span', 'qlabel', q.prompt_label),
      node('span', 'chip', labels[q.kind]), node('span', 'chip subtle', q.source.replaceAll('.md', '')));
    item.append(head, node('div', 'prompt latin', q.prompt), node('div', 'hint', q.meaning));
    for (const note of q.notes) item.append(node('p', 'hint', note));
    item.append(table(q, review));
    const inf = q.fields.find((field) => field.key === 'infinitive');
    if (inf) {
      const box = node('label', 'm-infinitive');
      box.append(node('span', 'flabel', inf.label), review ? resultCell(inf) : input(q, inf));
      item.append(box);
    }
    if (review) item.append(node('div', 'fullentry', q.full_entry));
    return item;
  }

  function showQuiz(data, title) {
    quiz = data;
    const form = $('#m-form');
    form.textContent = '';
    for (const q of data.questions) form.append(card(q));
    $('#m-title').textContent = title;
    error('#m-quiz-error');
    showView('quiz');
    form.querySelector('input:not(:disabled)')?.focus();
  }

  async function start() {
    save();
    $('#m-start').disabled = true;
    error('#m-setup-error');
    try {
      const data = await request('/api/morphology/quiz', settings());
      showQuiz(data, data.exhaustive ? 'Question sheet — every eligible entry' : 'Question sheet');
    } catch (exc) {
      error('#m-setup-error', exc.message);
    } finally {
      $('#m-start').disabled = false;
    }
  }

  function collect() {
    const answers = quiz.questions.map(() => ({ fields: {} }));
    for (const answer of document.querySelectorAll('#m-form input.answer:not(:disabled)')) {
      answers[parseInt(answer.dataset.index, 10)].fields[answer.dataset.key] = answer.value;
    }
    return answers;
  }

  async function submit() {
    if (submitting) return;
    submitting = true;
    $('#m-submit').disabled = true;
    error('#m-quiz-error');
    try {
      const data = await request('/api/grade', { id: quiz.id, answers: collect() });
      const score = data.score;
      const box = $('#m-score');
      box.textContent = '';
      box.append(node('div', 'bigscore', `${score.entry_correct} / ${score.entry_total}`),
        node('div', 'hint', `entries correct · ${score.field_correct} / ${score.field_total} forms correct`));
      const retest = $('#m-retest');
      retest.hidden = !score.missed;
      retest.textContent = `Retest the ${score.missed} I missed`;
      if (!score.missed) box.append(node('div', 'hint', 'Nothing to retest.'));
      const list = $('#m-result-list');
      list.textContent = '';
      for (const result of data.results) list.append(card(result, true));
      error('#m-results-error');
      showView('results');
    } catch (exc) {
      error('#m-quiz-error', exc.message);
    } finally {
      submitting = false;
      $('#m-submit').disabled = false;
    }
  }

  async function retest() {
    $('#m-retest').disabled = true;
    error('#m-results-error');
    try {
      const data = await request('/api/retest', { id: quiz.id });
      showQuiz(data, `Retest — ${data.questions.length} missed`);
    } catch (exc) {
      error('#m-results-error', exc.message);
    } finally {
      $('#m-retest').disabled = false;
    }
  }

  function setup() { showView('setup'); loadFiles(); }
  $('#m-start').addEventListener('click', start);
  $('#m-submit').addEventListener('click', submit);
  $('#m-retest').addEventListener('click', retest);
  $('#m-abandon').addEventListener('click', setup);
  $('#m-again').addEventListener('click', setup);
  $('#m-reload').addEventListener('click', loadFiles);
  $('#m-form').addEventListener('submit', (event) => { event.preventDefault(); submit(); });
  for (const [id, checked] of [['m-select-all', true], ['m-select-none', false]]) {
    $(`#${id}`).addEventListener('click', () => {
      document.querySelectorAll('#m-files input').forEach((cb) => { cb.checked = checked; });
      save(); refreshPool();
    });
  }
  document.querySelectorAll('#m-kinds input, #m-voice, #m-gender, #m-exhaustive, #m-shuffle')
    .forEach((control) => control.addEventListener('change', () => { save(); refreshPool(); }));
  $('#m-count').addEventListener('input', () => { save(); refreshPool(); });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || $('#m-quiz').hidden) return;
    if (event.ctrlKey || event.metaKey) { event.preventDefault(); submit(); return; }
    if (!event.target.matches('#m-form input.answer')) return;
    event.preventDefault();
    const inputs = [...document.querySelectorAll('#m-form input.answer:not(:disabled)')];
    const next = inputs.indexOf(document.activeElement) + 1;
    if (next < inputs.length) inputs[next].focus();
    else submit();
  });

  const saved = prefs();
  for (const name of ['voice', 'gender', 'count']) if (saved[name] !== undefined) $(`#m-${name}`).value = saved[name];
  for (const name of ['exhaustive', 'shuffle']) if (saved[name] !== undefined) $(`#m-${name}`).checked = saved[name];
  if (Array.isArray(saved.kinds)) document.querySelectorAll('#m-kinds input').forEach((cb) => { cb.checked = saved.kinds.includes(cb.value); });
  loadFiles();
})();
