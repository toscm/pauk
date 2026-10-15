// Settings dialog (docs/tutor.md 4.11): GET/PATCH learner/settings,
// plus the chat width, which belongs to this device (localStorage).

import { get, patch } from './api.js';
import { languageName, t } from './i18n.js';
import { h, toast } from './ui.js';

const SPACES = ['it', 'el', 'de', 'en'];
const immersion = () => [['off', t('settings.off')], ['partial', t('settings.immersion.partial')],
                         ['full', t('settings.immersion.full')]];
const itemCreation = () => [['off', t('settings.off')], ['propose', t('settings.propose')],
                            ['on_request', t('settings.creation.on_request')], ['free', t('settings.free')]];
const merge = () => [['propose', t('settings.propose')], ['free', t('settings.free')]];
const models = (current) => {
  const known = [['sonnet', t('settings.model.sonnet')], ['opus', t('settings.model.opus')], ['haiku', t('settings.model.haiku')]];
  return known.some(([v]) => v === current) ? known : [...known, [current, current]];
};

const WIDTH_KEY = 'pauk.width';
export const widths = () => [['full', t('settings.width.full')], ['wide', t('settings.width.wide')],
                             ['narrow', t('settings.width.narrow')]];

export function chatWidth() {
  let value = null;
  try { value = localStorage.getItem(WIDTH_KEY); } catch { /* storage blocked */ }
  return widths().some(([v]) => v === value) ? value : 'full';
}

export function applyWidth(value = chatWidth()) {
  try { localStorage.setItem(WIDTH_KEY, value); } catch { /* storage blocked */ }
  document.body.dataset.width = value;
}

function select(id, options, value) {
  return h('select', {id}, options.map(([v, label]) => h('option', {value: v, selected: v === value}, label)));
}

function field(id, label, control) {
  return h('div', {class: 'field'}, h('label', {for: id}, label), control);
}

function check(id, label, checked) {
  return h('div', {class: 'field check'}, h('input', {type: 'checkbox', id, checked: !!checked}), h('label', {for: id}, label));
}

export function settingsDialog(onLocalChange = () => {}) {
  const body = h('div', {});
  const error = h('p', {class: 'error', role: 'alert'});
  const save = h('button', {type: 'submit'}, t('settings.save'));
  const dialog = h('dialog', {class: 'settings', 'aria-labelledby': 'settings-title'},
    h('form', {}, h('h2', {id: 'settings-title'}, t('settings.title')), body, error,
      h('div', {class: 'buttons'}, save, h('button', {type: 'button', class: 'secondary', onclick: () => dialog.close()}, t('settings.cancel')))));
  document.body.append(dialog);
  let loaded = null;

  function fill(settings) {
    loaded = {'tutor.model': 'sonnet', ...settings};   // an older API has no tutor.model yet
    const chosen = settings['tutor.immersion'] || {};
    const spaces = [...new Set([...SPACES, ...Object.keys(chosen)])];
    body.replaceChildren(
      field('set-model', t('settings.model'), select('set-model', models(loaded['tutor.model']), loaded['tutor.model'])),
      h('p', {class: 'muted small'}, t('settings.model_note')),
      field('set-width', t('settings.width'), select('set-width', widths(), chatWidth())),
      field('set-language', t('settings.language'), h('input', {type: 'text', id: 'set-language', value: settings['tutor.language'] || ''})),
      h('fieldset', {}, h('legend', {}, t('settings.immersion')),
        spaces.map((space) => field(`set-imm-${space}`, `${languageName(space)} (${space})`,
          select(`set-imm-${space}`, immersion(), chosen[space] || 'off')))),
      field('set-creation', t('settings.creation'), select('set-creation', itemCreation(), settings['tutor.item_creation'])),
      field('set-merge', t('settings.merge'), select('set-merge', merge(), settings['tutor.merge'])),
      field('set-new', t('settings.new_items'), h('input', {type: 'number', id: 'set-new', min: 0, max: 50,
                                                           value: settings['tutor.new_items_per_15min'] ?? 8})),
      check('set-review', t('settings.review'), settings['review.after_session']),
      check('set-triage', t('settings.triage'), settings['review.auto_triage']));
  }

  function read() {
    const value = (id) => dialog.querySelector(`#${id}`);
    const immersion = {};
    for (const el of dialog.querySelectorAll('[id^="set-imm-"]')) {
      if (el.value !== 'off') immersion[el.id.slice('set-imm-'.length)] = el.value;
    }
    return {
      'tutor.model': value('set-model').value,
      'tutor.language': value('set-language').value.trim(),
      'tutor.immersion': immersion,
      'tutor.item_creation': value('set-creation').value,
      'tutor.merge': value('set-merge').value,
      'tutor.new_items_per_15min': Number(value('set-new').value),
      'review.after_session': value('set-review').checked,
      'review.auto_triage': value('set-triage').checked,
    };
  }

  dialog.querySelector('form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const width = dialog.querySelector('#set-width')?.value;
    if (width && width !== chatWidth()) {
      applyWidth(width);
      onLocalChange();
    }
    if (!loaded) return dialog.close();
    const changes = Object.fromEntries(Object.entries(read())
      .filter(([name, v]) => JSON.stringify(v) !== JSON.stringify(loaded[name])));
    if (!Object.keys(changes).length) return dialog.close();
    save.disabled = true;
    try {
      fill(await patch('learner/settings', changes));
      toast(t('settings.saved'));
      dialog.close();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      save.disabled = false;
    }
  });

  return {
    async open() {
      error.textContent = '';
      loaded = null;
      body.replaceChildren(h('p', {class: 'muted'}, t('app.loading')));
      dialog.showModal();
      try {
        fill(await get('learner/settings'));
      } catch (err) {
        error.textContent = err.message;
      }
    },
  };
}
