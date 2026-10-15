// The start screen: one tab per course with its level map (stages,
// units with stars, docs/tutor.md 9.6), and a "free session" tab with
// the subject picker (subjects, mode, minutes).

import { get, post } from './api.js';
import { local, t } from './i18n.js';
import { h, showError } from './ui.js';

const modes = () => [['learn', t('start.mode.learn')], ['review', t('start.mode.review')],
                     ['mixed', t('start.mode.mixed')], ['chat', t('start.mode.chat')]];
const unitModes = () => [['learn', t('start.mode.learn'), t('course.mode.learn')],
                         ['review', t('start.mode.review'), t('course.mode.review')],
                         ['mixed', t('start.mode.mixed'), t('course.mode.mixed')],
                         ['chat', t('start.mode.chat'), t('course.mode.chat')],
                         ['play', t('start.mode.play'), t('course.mode.play')],
                         ['exam', t('start.mode.exam'), t('course.mode.exam')]];
const TAB_KEY = 'pauk.start-tab';

export function modeName(mode) {
  return (unitModes().find(([value]) => value === mode) || [mode, mode])[1];
}

// "it, de · Mixed · 15 min", or for a unit "A1 · Being and having · Exam · 15 min".
export function goalText(goal) {
  if (goal.unit) {
    return t('start.goal', {dirs: `${goal.unit.stage.toUpperCase()} · ${local(goal.unit.title_local || goal.unit.title)}`,
                            mode: modeName(goal.mode), minutes: goal.minutes});
  }
  return t('start.goal', {dirs: (goal.dirs || []).join(', ') || t('start.all_subjects'), mode: modeName(goal.mode),
                          minutes: goal.minutes});
}

async function start(body, button) {
  button.disabled = true;
  try {
    await post('learner/start', body);
  } catch (error) {
    showError(error);
  } finally {
    button.disabled = false;
  }
}

export function startCard() {
  const panel = h('div', {class: 'start-panel'});
  const tabs = h('div', {class: 'tabs', role: 'tablist', 'aria-label': t('start.aria')});
  const card = h('section', {class: 'start-card', 'aria-label': t('start.aria')},
    h('h2', {}, t('start.title')), tabs, panel);
  let chosen = null;
  try { chosen = localStorage.getItem(TAB_KEY); } catch { /* storage blocked */ }

  function show(id, render) {
    chosen = id;
    try { localStorage.setItem(TAB_KEY, id); } catch { /* storage blocked */ }
    for (const tab of tabs.children) tab.setAttribute('aria-selected', String(tab.dataset.tab === id));
    panel.replaceChildren(render());
  }

  function tab(id, label, render) {
    return h('button', {type: 'button', role: 'tab', class: 'tab', 'data-tab': id, onclick: () => show(id, render)}, label);
  }

  panel.append(h('p', {class: 'muted small'}, t('course.loading')));
  get('learner/courses').then(({courses}) => {
    const all = [...courses.map((c) => [`course:${c.id}`, local(c.title), () => levelMap(c)]),
                 ['free', t('start.free'), freeForm]];
    tabs.replaceChildren(...all.map(([id, label, render]) => tab(id, label, render)));
    const [id, , render] = all.find(([id]) => id === chosen) || all[0];
    show(id, render);
  }).catch((error) => {
    showError(error);
    tabs.replaceChildren(tab('free', t('start.free'), freeForm));
    show('free', freeForm);
  });
  return card;
}

// --- level map ----------------------------------------------------------------

function starsText(n) {
  return '★'.repeat(n) + '☆'.repeat(3 - n);
}

function levelMap(course) {
  const rec = course.recommended;
  const dialog = unitDialog(course);
  const recUnit = rec && course.stages.find((s) => s.id === rec.stage)?.units.find((u) => u.id === rec.unit);
  const head = h('div', {class: 'course-head'},
    h('p', {class: 'muted small'}, t('course.intro')),
    recUnit ? h('button', {type: 'button', class: 'continue', onclick: () => dialog.open(rec.stage, recUnit)},
      t('course.continue', {unit: `${rec.stage.toUpperCase()} · ${local(recUnit.title)}`})) : null,
    course.imported ? null : h('p', {class: 'notice-box small'}, t('course.not_imported')));
  const stages = course.stages.map((stage, index) => {
    const started = stage.units.some((u) => u.seen > 0) || stage.id === rec?.stage || index === 0;
    const total = stage.units.length;
    return h('details', {class: 'stage', open: started},
      h('summary', {},
        h('span', {class: 'stage-title'}, local(stage.title)),
        h('span', {class: 'muted small'}, total ? t('course.passed', {n: stage.passed, total}) : ''),
        h('span', {class: 'bar', 'aria-hidden': 'true'}, h('span', {class: 'fill', style: `width: ${total ? Math.round(100 * stage.passed / total) : 0}%`}))),
      stage.description ? h('p', {class: 'muted small stage-desc'}, local(stage.description)) : null,
      h('ol', {class: 'units'}, stage.units.map((unit, i) => h('li', {},
        unitTile(stage, unit, i + 1, rec?.stage === stage.id && rec?.unit === unit.id, () => dialog.open(stage.id, unit))))));
  });
  return h('div', {class: 'level-map'}, head, stages);
}

function unitTile(stage, unit, number, recommended, onclick) {
  const classes = ['unit', `stars-${unit.stars}`, recommended ? 'recommended' : '', unit.refresh ? 'refresh' : ''].join(' ');
  return h('button', {type: 'button', class: classes, onclick,
                      'aria-label': `${stage.id.toUpperCase()}.${number} ${local(unit.title)}: ${t('course.stars', {n: unit.stars})}`},
    h('span', {class: 'unit-no'}, `${stage.id.toUpperCase()}.${number}`),
    h('span', {class: 'unit-title'}, local(unit.title)),
    h('span', {class: 'unit-stars', 'aria-hidden': 'true'}, starsText(unit.stars)),
    h('span', {class: 'bar', 'aria-hidden': 'true'}, h('span', {class: 'fill', style: `width: ${Math.round(100 * unit.share)}%`})),
    h('span', {class: 'unit-badges small'},
      recommended ? h('span', {class: 'badge rec'}, t('course.recommended')) : null,
      unit.refresh ? h('span', {class: 'badge refresh'}, t('course.refresh')) : null,
      unit.generated && !unit.items ? h('span', {class: 'badge gen'}, t('course.generated')) : null,
      unit.activity ? h('span', {class: 'badge game'}, t('course.game')) : null));
}

// The unit's details and the start: mode (suggested from progress) and minutes.
function unitDialog(course) {
  document.querySelector('dialog.unit-dialog')?.remove();
  const body = h('div', {});
  const dialog = h('dialog', {class: 'unit-dialog', 'aria-labelledby': 'unit-title'}, body);
  document.body.append(dialog);
  dialog.addEventListener('close', () => body.replaceChildren());

  function suggested(unit) {
    if (unit.refresh || unit.stars >= 2) return 'review';
    if (unit.seen === 0) return unit.activity ? 'play' : 'learn';
    return 'mixed';
  }

  return {
    open(stageId, unit) {
      const minutes = h('input', {type: 'number', id: 'unit-minutes', min: 5, max: 120, step: 5, value: 15});
      const button = h('button', {type: 'submit'}, t('start.start'));
      const choice = suggested(unit);
      const available = unitModes().filter(([value]) => value !== 'play' || unit.activity)
        .filter(([value]) => value !== 'review' || unit.seen > 0);
      const stats = unit.items
        ? t('course.stats', {learned: unit.learned, total: unit.items, due: unit.due})
        : unit.generated ? t('course.empty_generated') : t('course.empty');
      const form = h('form', {method: 'dialog'},
        h('div', {class: 'dialog-head'}, h('h2', {id: 'unit-title'}, `${stageId.toUpperCase()} · ${local(unit.title)}`),
          h('button', {type: 'button', class: 'secondary small', onclick: () => dialog.close()}, t('app.close'))),
        h('p', {}, h('span', {class: 'unit-stars big', 'aria-label': t('course.stars', {n: unit.stars})}, starsText(unit.stars)), ' ',
          h('span', {class: 'muted'}, stats)),
        h('p', {class: 'can-do'}, h('strong', {}, t('course.can_do')), ' ', local(unit.can_do)),
        unit.generated ? h('p', {class: 'muted small'}, t('course.generated_note')) : null,
        h('fieldset', {class: 'unit-modes'}, h('legend', {}, t('start.mode')),
          available.map(([value, label, help]) => h('label', {class: 'mode'},
            h('input', {type: 'radio', name: 'mode', value, checked: value === choice}),
            h('span', {}, h('strong', {}, label), h('span', {class: 'muted small'}, help))))),
        h('div', {class: 'field inline'}, h('label', {for: 'unit-minutes'}, t('start.minutes')), minutes),
        h('div', {class: 'buttons'}, button));
      if (!form.elements.mode.value) form.querySelector('input[name=mode]').checked = true;
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await start({mode: form.elements.mode.value, minutes: Number(minutes.value) || 15,
                     unit: {curriculum: course.id, stage: stageId, unit: unit.id}}, button);
        dialog.close();
      });
      body.replaceChildren(form);
      dialog.showModal();
      button.focus();
    },
  };
}

// --- free session ---------------------------------------------------------------

function freeForm() {
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

  const form = h('form', {},
    h('p', {class: 'muted small'}, t('start.intro')),
    h('div', {class: 'field'}, h('label', {for: 'subject-filter'}, t('start.subjects'), ' '), count, filter, list),
    h('fieldset', {class: 'modes'}, h('legend', {}, t('start.mode')),
      modes().map(([value, label]) => h('label', {}, h('input', {type: 'radio', name: 'mode', value, checked: value === 'mixed'}), ` ${label}`))),
    h('div', {class: 'field inline'}, h('label', {for: 'start-minutes'}, t('start.minutes')), minutes),
    h('div', {class: 'buttons'}, button));

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    start({dirs: [...chosen], mode: form.elements.mode.value, minutes: Number(minutes.value) || 15}, button);
  });
  return form;
}
