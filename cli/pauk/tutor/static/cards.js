// Transcript cards that are not exercises: item cards, proposals, the
// session summary, and the list of touched items (also in the side panel).

import { post } from './api.js';
import { t } from './i18n.js';
import { md, plain } from './md.js';
import { arrow, h, levelName, showError, toast } from './ui.js';

function imageUrl(value) {
  if (typeof value !== 'string' || !value) return null;
  try {
    const url = new URL(value, location.href);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function itemLine(item) {
  return [md(item.label_md, true), item.gloss_md ? [' — ', md(item.gloss_md, true)] : null,
          h('span', {class: 'muted small ref'}, ` ${item.ref}`)];
}

export function itemCard(ev) {
  const src = imageUrl(ev.attrs?.image);
  return h('section', {class: 'item-card', 'aria-label': t('cards.item_card')},
    ev.text_md ? md(ev.text_md) : null,
    h('div', {class: 'item-head'},
      h('strong', {class: 'label'}, md(ev.label_md, true)),
      h('span', {class: 'muted small'}, `${ev.kind} · ${ev.ref}`)),
    ev.gloss_md ? h('div', {class: 'gloss'}, md(ev.gloss_md, true)) : null,
    ev.body_md ? md(ev.body_md) : null,
    src ? h('img', {src, alt: plain(ev.label_md), loading: 'lazy'}) : null);
}

export class ProposalCard {
  constructor(ev) {
    this.id = ev.proposal_id;
    this.el = h('section', {class: 'proposal', 'aria-label': t('cards.proposal')});
    this.update(ev);
  }

  update(ev) {
    this.ev = ev;
    const candidates = ev.candidates || [];
    this.buttons = h('div', {class: 'buttons'},
      h('button', {type: 'button', onclick: () => this.decide(candidates.length ? 'add_anyway' : 'add')},
        candidates.length ? t('cards.add_anyway') : t('cards.add')),
      h('button', {type: 'button', class: 'secondary', onclick: () => this.decide('dismiss')}, t('cards.dismiss')));
    this.el.replaceChildren(...[
      h('p', {class: 'muted small'}, t('cards.proposes')),
      h('p', {class: 'proposed'}, itemLine(ev.item)),
      candidates.length ? h('p', {class: 'small'}, t('cards.similar')) : null,
      candidates.length ? h('ul', {class: 'candidates'}, candidates.map((c) => h('li', {},
        itemLine(c), ' ',
        h('button', {type: 'button', class: 'secondary small', onclick: () => this.decide('use_existing', c.ref)}, t('cards.use_existing'))))) : null,
      this.buttons].filter(Boolean));
  }

  async decide(action, ref) {
    try {
      await post('learner/proposal', {proposal_id: this.id, action, ...(ref ? {ref} : {})});
    } catch (e) {
      if (e.code === 'possible_duplicates' && e.data.candidates) {
        this.update({...this.ev, candidates: e.data.candidates});
        toast(t('cards.choose_again'));
      } else {
        showError(e);
      }
    }
  }

  resolved(ev) {
    for (const button of this.el.querySelectorAll('button')) button.disabled = true;
    const text = {add: t('cards.added', {ref: ev.ref}), add_anyway: t('cards.added', {ref: ev.ref}),
                  use_existing: t('cards.using_existing', {ref: ev.ref}), dismiss: t('cards.dismissed')}[ev.action] || ev.action;
    this.buttons.replaceChildren(h('span', {class: 'muted'}, text));
  }
}

export function touchedList(touched) {
  if (!touched.length) return h('p', {class: 'muted small'}, t('cards.nothing_yet'));
  return h('ul', {class: 'touched'}, touched.map((t) => h('li', {},
    md(t.label_md || t.ref, true), ' ',
    h('span', {class: `levels ${t.now > t.before ? 'up' : t.now < t.before ? 'down' : ''}`,
               title: `${levelName(t.before)} → ${levelName(t.now)}`},
      `${t.before} ${arrow(t.before, t.now)} ${t.now}`))));
}

export function summaryCard(ev) {
  return h('section', {class: 'summary', 'aria-label': t('cards.summary')},
    h('h2', {}, t('cards.summary')),
    md(ev.summary_md),
    ev.touched?.length ? [h('h3', {}, t('app.items_this_session')), touchedList(ev.touched)] : null);
}
