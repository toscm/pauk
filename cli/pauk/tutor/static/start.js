// The start card: subjects (filterable multi-select), mode, minutes.

import { get, post } from './api.js';
import { h, showError } from './ui.js';

const MODES = [['learn', 'Learn new'], ['review', 'Review'], ['mixed', 'Mixed'], ['chat', 'Free chat']];

export function startCard() {
  const chosen = new Set();
  const list = h('div', {class: 'subject-list', role: 'group', 'aria-label': 'Subjects'}, h('p', {class: 'muted small'}, 'Loading subjects…'));
  const count = h('span', {class: 'muted small', 'aria-live': 'polite'}, 'All subjects');
  const filter = h('input', {type: 'search', id: 'subject-filter', placeholder: 'Filter subjects', autocomplete: 'off'});
  const minutes = h('input', {type: 'number', id: 'start-minutes', min: 5, max: 120, step: 5, value: 15});
  const button = h('button', {type: 'submit'}, 'Start');

  function updateCount() {
    count.textContent = chosen.size ? `${chosen.size} selected` : 'All subjects';
  }

  filter.addEventListener('input', () => {
    const q = filter.value.trim().toLowerCase();
    for (const row of list.querySelectorAll('label')) row.hidden = !!q && !row.dataset.path.toLowerCase().includes(q);
  });

  get('learner/subjects').then(({items}) => {
    list.replaceChildren(...items.map((s) => h('label', {class: 'subject', 'data-path': s.path},
      h('input', {type: 'checkbox', value: s.path, onchange: (e) => {
        if (e.target.checked) chosen.add(s.path); else chosen.delete(s.path);
        updateCount();
      }}),
      s.path)));
    if (!items.length) list.replaceChildren(h('p', {class: 'muted small'}, 'No subjects yet.'));
  }).catch(showError);

  const form = h('form', {class: 'start-card', 'aria-label': 'Start a session'},
    h('h2', {}, 'What do you want to do?'),
    h('p', {class: 'muted small'}, 'Pick a goal, or just write to the teacher below.'),
    h('div', {class: 'field'}, h('label', {for: 'subject-filter'}, 'Subjects '), count, filter, list),
    h('fieldset', {class: 'modes'}, h('legend', {}, 'Mode'),
      MODES.map(([value, label]) => h('label', {}, h('input', {type: 'radio', name: 'mode', value, checked: value === 'mixed'}), ` ${label}`))),
    h('div', {class: 'field inline'}, h('label', {for: 'start-minutes'}, 'Minutes'), minutes),
    h('div', {class: 'buttons'}, button));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    button.disabled = true;
    try {
      await post('learner/start', {dirs: [...chosen], mode: form.elements.mode.value, minutes: Number(minutes.value) || 15});
    } catch (error) {
      showError(error);
    } finally {
      button.disabled = false;
    }
  });
  return form;
}
