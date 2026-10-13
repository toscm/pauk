// Read-only observer view: every event, including hidden keys, audit
// and annotation events, one compact line each with the JSON on demand.

import { get } from './api.js';
import { h, showError } from './ui.js';

function headline(ev) {
  if (ev.type === 'audit') return `${ev.command} ${Object.keys(ev.args || {}).length ? JSON.stringify(ev.args) : ''}`;
  if (ev.type === 'exercise') return `${ev.exercise_id} ${ev.kind}: ${ev.prompt_md}`;
  if (ev.type === 'drill') return `${ev.drill_id}: ${ev.exercises.length} exercises`;
  if (ev.type === 'answered') return `${ev.exercise_id} ${ev.response_md ?? JSON.stringify(ev.response)} ${'correct' in ev ? (ev.correct ? '✓' : '✗') : ''}`;
  const text = ev.text_md ?? ev.text ?? ev.summary_md ?? ev.reason ?? ev.label_md;
  return text === undefined ? '' : String(text);
}

function row(ev) {
  const {seq, at, from, type, ...rest} = ev;
  const time = new Date(at * 1000).toLocaleTimeString();
  return h('details', {class: `obs-row from-${from} type-${type}`},
    h('summary', {},
      h('span', {class: 'obs-seq'}, `#${seq}`), ' ',
      h('span', {class: 'muted'}, time), ' ',
      h('span', {class: 'obs-from'}, from), ' ',
      h('strong', {}, type), ' ',
      h('span', {class: 'obs-text'}, headline(ev).slice(0, 200))),
    h('pre', {}, JSON.stringify(rest, null, 2)));
}

export async function runObserver() {
  const status = h('p', {class: 'status', role: 'status'}, 'Loading…');
  const list = h('div', {class: 'obs-list'});
  const hideAudit = h('input', {type: 'checkbox', id: 'hide-audit', onchange: () => list.classList.toggle('hide-audit', hideAudit.checked)});
  document.body.classList.add('observer');
  document.body.replaceChildren(
    h('header', {class: 'top'}, h('h1', {}, 'pauk · observer'), status,
      h('div', {class: 'field check'}, hideAudit, h('label', {for: 'hide-audit'}, 'Hide audit events'))),
    h('main', {class: 'obs-main'}, list),
    h('div', {id: 'toasts', 'aria-live': 'polite'}));

  const add = (events) => {
    for (const ev of events) list.append(row(ev));
    if (events.length) list.lastElementChild.scrollIntoView({block: 'end'});
  };
  let last = 0;
  try {
    const state = await get('observer/state');
    status.textContent = `Session ${state.sid}${state.ended ? ' · ended' : ''} · read-only`;
    add(state.events);
    last = state.last_seq;
    if (state.ended) return;
  } catch (e) {
    status.textContent = 'Could not load the session.';
    showError(e);
    return;
  }
  for (;;) {
    try {
      const result = await get(`observer/wait?after=${last}&timeout=60`);
      add(result.events);
      last = result.last_seq;
      if (result.ended && !result.events.length) {
        status.textContent += ' · ended';
        return;
      }
    } catch (e) {
      showError(e);
      await new Promise((resolve) => setTimeout(resolve, 3000));
    }
  }
}
