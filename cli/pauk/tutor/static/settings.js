// Settings dialog (docs/tutor.md 4.11): GET/PATCH learner/settings.

import { get, patch } from './api.js';
import { h, toast } from './ui.js';

const SPACES = ['it', 'el', 'de', 'en'];
const IMMERSION = ['off', 'partial', 'full'];
const ITEM_CREATION = [['off', 'off'], ['propose', 'propose (ask me)'], ['on_request', 'only when I ask'], ['free', 'free']];
const MERGE = [['propose', 'propose (ask me)'], ['free', 'free']];

function select(id, options, value) {
  return h('select', {id}, options.map(([v, label]) => h('option', {value: v, selected: v === value}, label)));
}

function field(id, label, control) {
  return h('div', {class: 'field'}, h('label', {for: id}, label), control);
}

function check(id, label, checked) {
  return h('div', {class: 'field check'}, h('input', {type: 'checkbox', id, checked: !!checked}), h('label', {for: id}, label));
}

export function settingsDialog() {
  const body = h('div', {});
  const error = h('p', {class: 'error', role: 'alert'});
  const save = h('button', {type: 'submit'}, 'Save');
  const dialog = h('dialog', {class: 'settings', 'aria-labelledby': 'settings-title'},
    h('form', {}, h('h2', {id: 'settings-title'}, 'Settings'), body, error,
      h('div', {class: 'buttons'}, save, h('button', {type: 'button', class: 'secondary', onclick: () => dialog.close()}, 'Cancel'))));
  document.body.append(dialog);
  let loaded = null;

  function fill(settings) {
    loaded = settings;
    const immersion = settings['tutor.immersion'] || {};
    const spaces = [...new Set([...SPACES, ...Object.keys(immersion)])];
    body.replaceChildren(
      field('set-language', 'Teacher language (e.g. en, de, it)', h('input', {type: 'text', id: 'set-language', value: settings['tutor.language'] || ''})),
      h('fieldset', {}, h('legend', {}, 'Immersion per language'),
        spaces.map((space) => field(`set-imm-${space}`, space,
          select(`set-imm-${space}`, IMMERSION.map((v) => [v, v]), immersion[space] || 'off')))),
      field('set-creation', 'Teacher may add items', select('set-creation', ITEM_CREATION, settings['tutor.item_creation'])),
      field('set-merge', 'Teacher may merge duplicates', select('set-merge', MERGE, settings['tutor.merge'])),
      field('set-new', 'New items per 15 minutes', h('input', {type: 'number', id: 'set-new', min: 0, max: 50,
                                                               value: settings['tutor.new_items_per_15min'] ?? 8})),
      check('set-review', 'Review the session afterwards', settings['review.after_session']),
      check('set-triage', 'Triage reports automatically', settings['review.auto_triage']));
  }

  function read() {
    const value = (id) => dialog.querySelector(`#${id}`);
    const immersion = {};
    for (const el of dialog.querySelectorAll('[id^="set-imm-"]')) {
      if (el.value !== 'off') immersion[el.id.slice('set-imm-'.length)] = el.value;
    }
    return {
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
    if (!loaded) return dialog.close();
    const changes = Object.fromEntries(Object.entries(read())
      .filter(([name, v]) => JSON.stringify(v) !== JSON.stringify(loaded[name])));
    if (!Object.keys(changes).length) return dialog.close();
    save.disabled = true;
    try {
      fill(await patch('learner/settings', changes));
      toast('Settings saved.');
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
      body.replaceChildren(h('p', {class: 'muted'}, 'Loading…'));
      dialog.showModal();
      try {
        fill(await get('learner/settings'));
      } catch (err) {
        error.textContent = err.message;
      }
    },
  };
}
