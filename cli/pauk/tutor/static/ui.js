// Small DOM helpers shared by every module.

export const LEVELS = ['unseen', 'introduced', 'fragile', 'learning', 'known', 'mastered'];

// h('button', {class: 'x', onclick: fn}, 'text', child, ...) -> element.
// Attributes with null/undefined/false are skipped; true sets an empty attribute.
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key === 'class') el.className = value;
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

export function toast(text, kind = 'info') {
  const el = h('div', {class: `toast ${kind}`, role: kind === 'error' ? 'alert' : 'status'}, text);
  document.getElementById('toasts').append(el);
  setTimeout(() => el.remove(), kind === 'error' ? 8000 : 4000);
}

export function showError(error) {
  toast(error.message || String(error), 'error');
}

export function levelName(level) {
  return LEVELS[level] ?? String(level);
}

export function arrow(before, now) {
  return now > before ? '↑' : now < before ? '↓' : '→';
}

export function clock(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

// True while the user types somewhere (keyboard shortcuts stay off).
export function typing() {
  const el = document.activeElement;
  return !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));
}
