// Profile view: per-subject summary, what comes next, the item list,
// and suggested merges with Accept / Dismiss.

import { get, post } from './api.js';
import { md } from './md.js';
import { LEVELS, h, levelName, showError, toast } from './ui.js';

function percent(x) {
  return x === null || x === undefined ? '–' : `${Math.round(x * 100)}%`;
}

function summaryView(summary) {
  const total = Math.max(1, summary.items);
  return h('div', {class: 'profile-summary'},
    h('p', {}, `${summary.items} items · coverage ${percent(summary.coverage)} · ${summary.due} due`),
    h('ul', {class: 'levels-bars'}, LEVELS.map((name, level) => {
      const n = summary.by_mastery?.[level] ?? 0;
      return h('li', {},
        h('span', {class: 'level-name'}, `${level} ${name}`),
        h('span', {class: 'bar', 'aria-hidden': 'true'}, h('span', {class: `fill l${level}`, style: `width: ${(100 * n) / total}%`})),
        h('span', {class: 'level-count'}, String(n)));
    })));
}

function nextList(title, entries) {
  return h('div', {}, h('h4', {}, title), entries.length
    ? h('ul', {class: 'plain'}, entries.map((e) => h('li', {},
        md(e.label_md, true), e.gloss_md ? [' — ', md(e.gloss_md, true)] : null,
        h('span', {class: 'muted small'}, ` ${e.reason || ''}`))))
    : h('p', {class: 'muted small'}, 'Nothing.'));
}

function itemsTable(items) {
  if (!items.length) return h('p', {class: 'muted small'}, 'No items.');
  return h('table', {class: 'items'},
    h('thead', {}, h('tr', {}, h('th', {scope: 'col'}, 'Item'), h('th', {scope: 'col'}, 'Level'), h('th', {scope: 'col'}, 'Recall'))),
    h('tbody', {}, items.map((item) => h('tr', {},
      h('td', {}, md(item.label_md, true), item.gloss_md ? h('div', {class: 'muted small'}, md(item.gloss_md, true)) : null,
        h('div', {class: 'muted small ref'}, item.ref)),
      h('td', {}, levelName(item.state?.mastery ?? 0)),
      h('td', {}, percent(item.state?.recall))))));
}

export function profileDialog() {
  const subject = h('select', {id: 'profile-subject'}, h('option', {value: ''}, 'All subjects'));
  const search = h('input', {type: 'search', id: 'profile-q', placeholder: 'Search items', autocomplete: 'off'});
  const summary = h('div', {});
  const next = h('div', {class: 'next-lists'});
  const items = h('div', {});
  const merges = h('div', {});
  const dialog = h('dialog', {class: 'profile wide', 'aria-labelledby': 'profile-title'},
    h('div', {class: 'dialog-head'}, h('h2', {id: 'profile-title'}, 'Knowledge profile'),
      h('button', {type: 'button', class: 'secondary', onclick: () => dialog.close()}, 'Close')),
    h('div', {class: 'field inline'}, h('label', {for: 'profile-subject'}, 'Subject'), subject),
    h('h3', {}, 'Summary'), summary,
    h('h3', {}, 'Next'), next,
    h('h3', {}, 'Items'), h('div', {class: 'field'}, h('label', {for: 'profile-q', class: 'sr-only'}, 'Search items'), search), items,
    h('h3', {}, 'Suggested merges'), merges);
  document.body.append(dialog);
  let subjectsLoaded = false;
  let searchTimer = null;

  async function loadItems() {
    const params = new URLSearchParams(Object.entries({dir: subject.value, q: search.value.trim()}).filter(([, v]) => v));
    try {
      items.replaceChildren(itemsTable((await get(`learner/items?${params}`)).items));
    } catch (e) {
      showError(e);
    }
  }

  async function loadSubject() {
    summary.replaceChildren(h('p', {class: 'muted'}, 'Loading…'));
    try {
      const profile = await get(subject.value ? `learner/profile?dir=${encodeURIComponent(subject.value)}` : 'learner/profile');
      summary.replaceChildren(summaryView(profile.summary));
      next.replaceChildren(nextList('Due for review', profile.next.review || []), nextList('New next', profile.next.new || []));
    } catch (e) {
      summary.replaceChildren();
      showError(e);
    }
    await loadItems();
  }

  async function decideMerge(merge, action) {
    try {
      await post(`learner/merges/${merge.id}/${action}`);
      toast(action === 'accept' ? `Merged ${merge.from} into ${merge.into}.` : 'Suggestion dismissed.');
      await loadMerges();
    } catch (e) {
      showError(e);
    }
  }

  async function loadMerges() {
    try {
      const list = (await get('learner/merges')).items;
      merges.replaceChildren(list.length ? h('ul', {class: 'plain merges'}, list.map((m) => h('li', {},
        h('div', {}, md(m.from_label_md || m.from, true), ` (${m.from}) → `, md(m.into_label_md || m.into, true), ` (${m.into})`),
        h('div', {class: 'muted small'}, `${m.reason} — suggested by ${m.suggested_by}`),
        h('div', {class: 'buttons'},
          h('button', {type: 'button', class: 'small', onclick: () => decideMerge(m, 'accept')}, 'Accept'),
          h('button', {type: 'button', class: 'secondary small', onclick: () => decideMerge(m, 'dismiss')}, 'Dismiss')))))
        : h('p', {class: 'muted small'}, 'No suggestions.'));
    } catch (e) {
      showError(e);
    }
  }

  subject.addEventListener('change', loadSubject);
  search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadItems, 250);
  });

  return {
    async open(defaultDir) {
      dialog.showModal();
      if (!subjectsLoaded) {
        try {
          const {items: subjects} = await get('learner/subjects');
          subject.append(...subjects.map((s) => h('option', {value: s.path}, s.path)));
          subjectsLoaded = true;
          if (defaultDir) subject.value = defaultDir;
        } catch (e) {
          showError(e);
        }
      }
      await Promise.all([loadSubject(), loadMerges()]);
    },
  };
}
