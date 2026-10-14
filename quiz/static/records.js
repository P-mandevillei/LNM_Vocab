'use strict';

// Shared record controls and review grouping for both local testers.
window.LatinRecords = {
  async init(kind, getQuiz, restore) {
    const error = document.querySelector('#record-error');
    const showError = (message) => { error.textContent = message; error.hidden = !message; };
    async function accept(data) {
      if (data.kind !== kind) {
        sessionStorage.setItem('latin-restored-test', JSON.stringify(data));
        window.location.href = data.kind === 'morphology' ? '/morphology.html' : '/';
        return;
      }
      await restore(data);
    }
    document.querySelector('#record-upload').addEventListener('change', async (event) => {
      showError('');
      try {
        const file = event.target.files[0];
        if (!file) return;
        if (file.size > 20 * 1024 * 1024) throw new Error('Test record is too large (maximum 20 MB).');
        let record;
        try { record = JSON.parse((await file.text()).replace(/^\uFEFF/, '')); }
        catch { throw new Error('The file is not a valid JSON test record.'); }
        const response = await fetch('/api/record/restore', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ record }),
        });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || 'Could not restore the record.');
        await accept(data);
      } catch (exc) { showError(exc.message); }
      finally { event.target.value = ''; }
    });
    for (const button of document.querySelectorAll('[data-download-record]')) {
      button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          const response = await fetch('/api/record', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: getQuiz().id }),
          });
          const record = await response.json();
          if (!response.ok || record.error) throw new Error(record.error || 'Could not download the record.');
          const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: 'application/json' }));
          const link = document.createElement('a');
          link.href = url;
          link.download = `latin-${kind}-${record.retest ? 'retest' : 'test'}-record.json`;
          link.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (exc) { alert(exc.message); }
        finally { button.disabled = false; }
      });
    }
    const pending = sessionStorage.getItem('latin-restored-test');
    if (pending) {
      sessionStorage.removeItem('latin-restored-test');
      try { await accept(JSON.parse(pending)); }
      catch (exc) { showError(exc.message); }
    }
  },

  unfamiliar(index) {
    const label = document.createElement('label');
    label.className = 'inline unfamiliar-control';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.dataset.unfamiliar = index;
    input.setAttribute('aria-label', `Entry ${index + 1}: unfamiliar`);
    label.append(input, document.createTextNode(' Unfamiliar'));
    return label;
  },

  collectUnfamiliar(form, answers) {
    for (const input of form.querySelectorAll('[data-unfamiliar]')) {
      answers[Number(input.dataset.unfamiliar)].unfamiliar = input.checked;
    }
  },

  review(list, results, card) {
    list.textContent = '';
    const unfamiliar = results.filter((r) => r.unfamiliar);
    const wrong = (r) => r.verdict === 'wrong' || r.fields.some((f) => f.verdict === 'wrong');
    const remaining = results.filter((r) => !r.unfamiliar).sort((a, b) => Number(wrong(b)) - Number(wrong(a)));
    const heading = document.createElement(unfamiliar.length ? 'h3' : 'p');
    heading.textContent = unfamiliar.length ? `Unfamiliar entries (${unfamiliar.length})` : 'No entries marked unfamiliar.';
    list.append(heading);
    for (const r of unfamiliar) list.append(card(r));
    if (remaining.length) {
      const details = document.createElement('details');
      details.className = 'remaining-entries';
      const summary = document.createElement('summary');
      summary.textContent = `Remaining entries (${remaining.length}) — wrong answers first`;
      details.append(summary);
      for (const r of remaining) details.append(card(r));
      list.append(details);
    }
  },

  retestControls(select, button, counts) {
    const labels = { wrong: 'Wrong entries only', unfamiliar: 'Unfamiliar entries only', combined: 'Unfamiliar + wrong entries' };
    for (const option of select.options) option.textContent = `${labels[option.value]} (${counts[option.value]})`;
    const update = () => {
      const count = counts[select.value];
      button.hidden = false;
      button.disabled = !count;
      button.textContent = count ? (select.value === 'wrong' ? `Retest the ${count} I missed` : `Retest ${count} ${count === 1 ? 'entry' : 'entries'}`) : 'Nothing to retest for this selection';
    };
    select.onchange = update;
    update();
  },
};
