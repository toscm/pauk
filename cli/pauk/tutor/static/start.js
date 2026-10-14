// The start card: subjects (filterable multi-select), mode, minutes.

import { get, post } from './api.js';
import { t } from './i18n.js';
import { h, showError } from './ui.js';

const modes = () => [['learn', t('start.mode.learn')], ['review', t('start.mode.review')],
                     ['mixed', t('start.mode.mixed')], ['chat', t('start.mode.chat')]];

export function modeName(mode) {
  return (modes().find(([value]) => value === mode) || [mode, mode])[1];
}

// "it, de · Mixed · 15 min" for a goal {dirs, mode, minutes}.
export function goalText(goal) {
  return t('start.goal', {dirs: (goal.dirs || []).join(', ') || t('start.all_subjects'), mode: modeName(goal.mode),
                          minutes: goal.minutes});
}

export function startCard() {
  const chosen = new Set();
  const list = h('div', {class: 'subject-list', role: 'group', 'aria-label': t('start.subjects')},
    h('p', {class: 'muted small'}, t('start.loading_subjects')));
  const count = h('span', {class: 'muted small', 'aria-live': 'polite'}, t('start.all_subjects'));
  const filter = h('input', {type: 'search', id: 'subject-filter', placeholder: t('start.filter'), autocomplete: 'off'});
  const minutes = h('input', {type: 'number', id: 'start-minutes', min: 5, max: 120, step: 5, value: 15});
  const button = h('button', {type: 'submit'}, t('start.start'));

  function updateCount() {
    count.textContent = chosen.size ? t('start.selected', {n: chosen.size}) : t('start.all_subjects');
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
    if (!items.length) list.replaceChildren(h('p', {class: 'muted small'}, t('start.no_subjects')));
  }).catch(showError);

  const form = h('form', {class: 'start-card', 'aria-label': t('start.aria')},
    h('h2', {}, t('start.title')),
    h('p', {class: 'muted small'}, t('start.intro')),
    h('div', {class: 'field'}, h('label', {for: 'subject-filter'}, t('start.subjects'), ' '), count, filter, list),
    h('fieldset', {class: 'modes'}, h('legend', {}, t('start.mode')),
      modes().map(([value, label]) => h('label', {}, h('input', {type: 'radio', name: 'mode', value, checked: value === 'mixed'}), ` ${label}`))),
    h('div', {class: 'field inline'}, h('label', {for: 'start-minutes'}, t('start.minutes')), minutes),
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
