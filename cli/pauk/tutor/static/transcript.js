// The chat transcript: renders every learner-visible event type,
// dedupes by seq, routes updates to exercise widgets and proposal
// cards, and tracks what the status line needs.

import { activityCard } from './activity.js';
import { ProposalCard, itemCard, summaryCard } from './cards.js';
import { Drill, ExerciseWidget } from './exercises.js';
import { t } from './i18n.js';
import { md } from './md.js';
import { goalText } from './start.js';
import { arrow, h } from './ui.js';

// Learner events after which the teacher is expected to respond.
const AWAITS_TEACHER = new Set(['learner_message', 'start', 'hint_request', 'end']);

export class Transcript {
  constructor(container, {onReport, onChange}) {
    this.container = container;
    this.onReport = onReport;
    this.onChange = onChange;
    this.seen = new Set();
    this.events = [];              // everything shown so far, for rebuild()
    this.widgets = new Map();      // exercise_id -> ExerciseWidget
    this.proposals = new Map();    // proposal_id -> ProposalCard
    this.activities = new Map();   // aid -> activity card
    this.teacherSeen = false;      // any teacher event so far
    this.awaiting = false;         // the learner acted, the teacher has not answered yet
    this.ended = false;
  }

  // Render every event again (after a UI language change), keeping
  // what the learner has typed into open exercises.
  rebuild() {
    const typed = new Map([...this.widgets].filter(([, w]) => w.input && !w.locked).map(([id, w]) => [id, w.input.value]));
    const events = this.events;
    this.seen = new Set();
    this.events = [];
    this.widgets = new Map();
    this.proposals = new Map();
    this.activities = new Map();
    this.teacherSeen = false;
    this.awaiting = false;
    this.ended = false;
    this.container.replaceChildren();
    for (const ev of events) this.add(ev, false);
    for (const [id, value] of typed) {
      const w = this.widgets.get(id);
      if (w?.input && !w.locked) w.input.value = value;
    }
  }

  add(ev, live) {
    if (this.seen.has(ev.seq)) return;
    this.seen.add(ev.seq);
    this.events.push(ev);
    this.track(ev);
    const node = this.render(ev, live);
    if (node) {
      const entry = h('article', {class: `entry from-${ev.from} type-${ev.type}`, 'data-seq': ev.seq},
        node,
        h('button', {type: 'button', class: 'flag', title: t('transcript.flag'),
                     'aria-label': t('transcript.flag_entry', {seq: ev.seq}), onclick: () => this.onReport(ev.seq)}, '⚑'));
      this.container.append(entry);
      if (live) entry.scrollIntoView({block: 'end', behavior: 'smooth'});
      if (live && (ev.type === 'exercise' || ev.type === 'drill')) entry.querySelector('.exercise')?.querySelector('input, textarea, select, button')?.focus({preventScroll: true});
    }
    this.onChange(ev, live);
  }

  track(ev) {
    if (ev.from === 'teacher') {
      this.teacherSeen = true;
      this.awaiting = false;
    } else if (ev.from === 'learner' && (AWAITS_TEACHER.has(ev.type) || (ev.type === 'answered' && !ev.drill_id))) {
      this.awaiting = true;
    } else if (ev.type === 'drill_done') {
      this.awaiting = true;
    }
    if (ev.type === 'ended') this.ended = true;
  }

  // The newest open text/open exercise on screen: the composer answers it.
  answerTarget() {
    return [...this.widgets.values()].reverse().find((w) => w.acceptsText) || null;
  }

  register(widget) {
    this.widgets.set(widget.id, widget);
    return widget;
  }

  render(ev, live) {
    const widget = this.widgets.get(ev.exercise_id);
    switch (ev.type) {
      case 'message':
        return h('div', {class: 'bubble teacher'}, md(ev.text_md));
      case 'learner_message':
        return h('div', {class: 'bubble learner'}, md(ev.text));
      case 'item_card':
        return itemCard(ev);
      case 'exercise':
        return this.register(new ExerciseWidget(ev)).el;
      case 'drill':
        return new Drill(ev, (w) => this.register(w)).el;
      case 'answered':
        widget?.answered(ev, live);
        return null;
      case 'graded':
        widget?.graded(ev);
        return null;
      case 'override':
        widget?.overridden(ev);
        return null;
      case 'hint':
        widget?.hinted(ev);
        return null;
      case 'hint_request':
        widget?.hintRequested();
        return null;
      case 'reveal':
        widget?.revealed(ev.reference_md);
        return null;
      case 'proposal': {
        const existing = this.proposals.get(ev.proposal_id);
        if (existing) {
          existing.update(ev);
          return null;
        }
        const card = new ProposalCard(ev);
        this.proposals.set(card.id, card);
        return card.el;
      }
      case 'activity': {
        const card = activityCard(ev);
        this.activities.set(card.aid, card);
        return card.el;
      }
      case 'activity_update':
        this.activities.get(ev.aid)?.update(ev);
        return null;
      case 'activity_done':
        this.activities.get(ev.aid)?.done(ev);
        return null;
      case 'item_proposal_resolved':
        this.proposals.get(ev.proposal_id)?.resolved(ev);
        return null;
      case 'summary':
        return summaryCard(ev);
      default:
        return this.notice(ev);
    }
  }

  // Small one-line entries; null for unknown or uninteresting events.
  notice(ev) {
    const text = (...parts) => h('p', {class: 'notice'}, ...parts);
    switch (ev.type) {
      case 'start':
        return text(t('transcript.goal', {goal: goalText(ev.goal || {})}));
      case 'item_added':
        return text(t('transcript.item_added'), ' ', md(ev.label_md, true), ` (${ev.ref})`);
      case 'level_change':
        return text(ev.changes.map((c, i) => [i ? ', ' : '', md(c.label_md || c.ref, true), ` ${c.before} ${arrow(c.before, c.now)} ${c.now}`]));
      case 'flag':
        return text(md(ev.label_md || ev.ref, true), ' ', t('transcript.flagged', {status: ev.status}));
      case 'merge':
        return text(t('transcript.merged', {from: ev.merge.from, into: ev.merge.into}));
      case 'report':
        return text(ev.stored === 'api' ? t('transcript.report_server', {category: ev.category})
                                        : t('transcript.report_local', {category: ev.category}));
      case 'status':
        if (ev.teacher_connected) return text(ev.agent ? t('transcript.teacher_connected_as', {agent: ev.agent}) : t('transcript.teacher_connected'));
        if (ev.agent_running !== false) return null;
        return text(ev.detail ? t('transcript.teacher_disconnected_because', {detail: ev.detail}) : t('transcript.teacher_disconnected'));
      case 'settings_changed':
        return text(t('transcript.settings_updated'));
      case 'time_warning':
        return text(t('transcript.time_warning', {minutes: ev.minutes_left}));
      case 'end':
        return text(t('transcript.learner_ended'));
      case 'idle':
        return text(t('transcript.idle', {minutes: Math.round(ev.idle_s / 60)}));
      case 'ended':
        return text(t('transcript.ended'));
      default:
        return null;
    }
  }
}
