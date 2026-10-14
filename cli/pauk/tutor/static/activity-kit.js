// Shared helpers for the activity renderers (activity.js and one
// module per activity type): SVG elements, the one act endpoint, and
// re-rendering without losing what the learner is typing.

import { post } from './api.js';
import { showError } from './ui.js';

const SVG = 'http://www.w3.org/2000/svg';

export function s(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value);
  }
  el.append(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return el;
}

// Every click goes through POST learner/activity, exactly what an agent
// sends; the new state arrives as an activity_update event.
export async function act(aid, action, card) {
  card.busy(true);
  try {
    await post('learner/activity', {aid, action});
    return true;
  } catch (e) {
    showError(e);
    return false;
  } finally {
    card.busy(false);
  }
}

// Clickable SVG group: mouse, Enter and Space.
export function pressable(label, onpress) {
  return {role: 'button', tabindex: 0, 'aria-label': label, onclick: onpress,
          onkeydown: (e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onpress())};
}

// Replace the card's content, keeping the text of inputs marked with
// data-keep and the focus (by data-keep or data-focus key).
export function rerender(el, children) {
  const kept = {};
  for (const input of el.querySelectorAll('[data-keep]')) kept[input.dataset.keep] = input.value;
  const active = el.contains(document.activeElement) ? document.activeElement : null;
  const focusKey = active?.dataset.keep || active?.dataset.focus || null;
  el.replaceChildren(...children.filter(Boolean));
  for (const input of el.querySelectorAll('[data-keep]')) {
    if (kept[input.dataset.keep] !== undefined) input.value = kept[input.dataset.keep];
  }
  if (focusKey) {
    const target = el.querySelector(`[data-keep="${focusKey}"], [data-focus="${focusKey}"]`);
    target?.focus();
  }
}

export function speaker(ev) {
  return ev.from === 'teacher' ? 'Teacher' : ev.from === 'learner' ? 'You' : 'pauk';
}
