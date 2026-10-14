// UI language (issue 0017): the browser's fixed strings come from a
// message catalogue per language, `i18n/<lang>.js` (`export default
// {'id': 'text with {param}', ...}`), chosen from the learner's
// `tutor.language` setting with English as the fallback. Adding a
// language is adding its file. Activity summaries arrive as
// `{id, params}` messages (cli/pauk/tutor/activities/common.py Msg);
// content texts may be translations keyed by language tag.

import en from './i18n/en.js';

let lang = 'en';
let catalogue = en;

export function language() {
  return lang;
}

function primary(tag) {
  const code = String(tag || '').trim().toLowerCase().split(/[-_]/)[0];
  return /^[a-z]{2,3}$/.test(code) ? code : 'en';
}

// Switches the catalogue; resolves to true when the language changed.
export async function setLanguage(tag) {
  const want = primary(tag);
  if (want === lang) return false;
  let next = en;
  if (want !== 'en') {
    try {
      next = (await import(`./i18n/${want}.js`)).default;
    } catch {
      next = en;   // no catalogue for this language
    }
  }
  const changed = next !== catalogue;
  catalogue = next;
  lang = next === en ? 'en' : want;
  document.documentElement.lang = lang;
  translatePage();
  return changed;
}

// A content text: a string, or translations keyed by language tag.
export function local(value) {
  if (value === null || value === undefined || typeof value !== 'object') return value;
  return value[lang] ?? value.en ?? Object.values(value)[0];
}

// t(id, {name: 'x'}) -> the text in the UI language, placeholders
// filled; parameters may be content texts with translations.
export function t(id, params = {}) {
  const text = catalogue[id] ?? en[id] ?? id;
  return text.replace(/\{(\w+)\}/g, (m, key) => (key in params ? String(local(params[key]) ?? '') : m));
}

// A message from the host ({id, params}), or the English fallback text.
export function message(msg, fallback = '') {
  return msg && msg.id && (catalogue[msg.id] || en[msg.id]) ? t(msg.id, msg.params || {}) : fallback;
}

// The name of a language in the UI language ("it" -> "Italienisch").
export function languageName(code) {
  try {
    return new Intl.DisplayNames([lang], {type: 'language'}).of(code) || code;
  } catch {
    return code;
  }
}

// Static markup: data-i18n (text), data-i18n-placeholder, -title, -aria-label.
export function translatePage(root = document) {
  for (const el of root.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n);
  for (const attr of ['placeholder', 'title', 'aria-label']) {
    for (const el of root.querySelectorAll(`[data-i18n-${attr}]`)) el.setAttribute(attr, t(el.getAttribute(`data-i18n-${attr}`)));
  }
}
