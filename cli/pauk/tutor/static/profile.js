// Profile view: per-subject summary, what comes next, the item list,
// and suggested merges with Accept / Dismiss.

import { get, post } from './api.js';
import { t } from './i18n.js';
import { md } from './md.js';
import { LEVELS, h, levelName, showError, toast } from './ui.js';

function percent(x) {
  return x === null || x === undefined ? '–' : `${Math.round(x * 100)}%`;
}

function summaryView(summary) {
  const total = Math.max(1, summary.items);
  return h('div', {class: 'profile-summary'},
    h('p', {}, t('profile.summary', {items: summary.items, coverage: percent(summary.coverage), due: summary.due})),
    h('ul', {class: 'levels-bars'}, LEVELS.map((name, level) => {
      const n = summary.by_mastery?.[level] ?? 0;
      return h('li', {},
        h('span', {class: 'level-name'}, `${level} ${levelName(level)}`),
        h('span', {class: 'bar', 'aria-hidden': 'true'}, h('span', {class: `fill l${level}`, style: `width: ${(100 * n) / total}%`})),
        h('span', {class: 'level-count'}, String(n)));
    })));
}

function nextList(title, entries) {
  return h('div', {}, h('h4', {}, title), entries.length
    ? h('ul', {class: 'plain'}, entries.map((e) => h('li', {},
        md(e.label_md, true), e.gloss_md ? [' — ', md(e.gloss_md, true)] : null,
        h('span', {class: 'muted small'}, ` ${e.reason || ''}`))))
    : h('p', {class: 'muted small'}, t('profile.nothing')));
}

function itemsTable(items) {
  if (!items.length) return h('p', {class: 'muted small'}, t('profile.no_items'));
  return h('table', {class: 'items'},
    h('thead', {}, h('tr', {}, h('th', {scope: 'col'}, t('profile.item')), h('th', {scope: 'col'}, t('profile.level')),
                    h('th', {scope: 'col'}, t('profile.recall')))),
    h('tbody', {}, items.map((item) => h('tr', {},
      h('td', {}, md(item.label_md, true), item.gloss_md ? h('div', {class: 'muted small'}, md(item.gloss_md, true)) : null,
        h('div', {class: 'muted small ref'}, item.ref)),
      h('td', {}, levelName(item.state?.mastery ?? 0)),
      h('td', {}, percent(item.state?.recall))))));
}

export function profileDialog() {
  const subject = h('select', {id: 'profile-subject'}, h('option', {value: ''}, t('start.all_subjects')));
  const search = h('input', {type: 'search', id: 'profile-q', placeholder: t('profile.search'), autocomplete: 'off'});
  const summary = h('div', {});
  const next = h('div', {class: 'next-lists'});
  const items = h('div', {});
  const merges = h('div', {});
  const dialog = h('dialog', {class: 'profile wide', 'aria-labelledby': 'profile-title'},
    h('div', {class: 'dialog-head'}, h('h2', {id: 'profile-title'}, t('profile.title')),
      h('button', {type: 'button', class: 'secondary', onclick: () => dialog.close()}, t('profile.close'))),
    h('div', {class: 'field inline'}, h('label', {for: 'profile-subject'}, t('profile.subject')), subject),
    h('h3', {}, t('profile.summary_title')), summary,
    h('h3', {}, t('profile.next')), next,
    h('h3', {}, t('profile.items')), h('div', {class: 'field'}, h('label', {for: 'profile-q', class: 'sr-only'}, t('profile.search')), search), items,
    h('h3', {}, t('profile.merges')), merges);
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
    summary.replaceChildren(h('p', {class: 'muted'}, t('app.loading')));
    try {
      const profile = await get(subject.value ? `learner/profile?dir=${encodeURIComponent(subject.value)}` : 'learner/profile');
      summary.replaceChildren(summaryView(profile.summary));
      next.replaceChildren(nextList(t('profile.due'), profile.next.review || []), nextList(t('profile.new_next'), profile.next.new || []));
    } catch (e) {
      summary.replaceChildren();
      showError(e);
    }
    await loadItems();
  }

  async function decideMerge(merge, action) {
    try {
      await post(`learner/merges/${merge.id}/${action}`);
      toast(action === 'accept' ? t('transcript.merged', {from: merge.from, into: merge.into}) : t('profile.merge_dismissed'));
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
        h('div', {class: 'muted small'}, t('profile.suggested_by', {reason: m.reason, by: m.suggested_by})),
        h('div', {class: 'buttons'},
          h('button', {type: 'button', class: 'small', onclick: () => decideMerge(m, 'accept')}, t('profile.accept')),
          h('button', {type: 'button', class: 'secondary small', onclick: () => decideMerge(m, 'dismiss')}, t('cards.dismiss'))))))
        : h('p', {class: 'muted small'}, t('profile.no_merges')));
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
