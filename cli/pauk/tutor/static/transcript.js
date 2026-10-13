// The chat transcript: renders every learner-visible event type,
// dedupes by seq, routes updates to exercise widgets and proposal
// cards, and tracks what the status line needs.

import { activityCard } from './activity.js';
import { ProposalCard, itemCard, summaryCard } from './cards.js';
import { Drill, ExerciseWidget } from './exercises.js';
import { md } from './md.js';
import { arrow, h } from './ui.js';

// Learner events after which the teacher is expected to respond.
const AWAITS_TEACHER = new Set(['learner_message', 'start', 'hint_request', 'end']);

export class Transcript {
  constructor(container, {onReport, onChange}) {
    this.container = container;
    this.onReport = onReport;
    this.onChange = onChange;
    this.seen = new Set();
    this.widgets = new Map();      // exercise_id -> ExerciseWidget
    this.proposals = new Map();    // proposal_id -> ProposalCard
    this.activities = new Map();   // aid -> activity card
    this.teacherSeen = false;      // any teacher event so far
    this.awaiting = false;         // the learner acted, the teacher has not answered yet
    this.ended = false;
  }

  add(ev, live) {
    if (this.seen.has(ev.seq)) return;
    this.seen.add(ev.seq);
    this.track(ev);
    const node = this.render(ev, live);
    if (node) {
      const entry = h('article', {class: `entry from-${ev.from} type-${ev.type}`, 'data-seq': ev.seq},
        node,
        h('button', {type: 'button', class: 'flag', title: 'Report a problem with this',
                     'aria-label': `Report a problem with entry ${ev.seq}`, onclick: () => this.onReport(ev.seq)}, '⚑'));
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
      case 'start': {
        const g = ev.goal || {};
        return text(`Goal: ${(g.dirs || []).join(', ') || 'all subjects'} · ${g.mode} · ${g.minutes} min`);
      }
      case 'item_added':
        return text('New item added: ', md(ev.label_md, true), ` (${ev.ref})`);
      case 'level_change':
        return text(ev.changes.map((c, i) => [i ? ', ' : '', md(c.label_md || c.ref, true), ` ${c.before} ${arrow(c.before, c.now)} ${c.now}`]));
      case 'flag':
        return text(md(ev.label_md || ev.ref, true), ` is now marked ${ev.status}.`);
      case 'merge':
        return text(`Merged ${ev.merge.from} into ${ev.merge.into}.`);
      case 'report':
        return text(`Problem report (${ev.category}) stored ${ev.stored === 'api' ? 'on the server' : 'locally'}.`);
      case 'status':
        if (ev.teacher_connected) return text(`Teacher connected${ev.agent ? ` (${ev.agent})` : ''}.`);
        return ev.agent_running === false ? text(`Teacher disconnected${ev.detail ? `: ${ev.detail}` : ''}.`) : null;
      case 'settings_changed':
        return text('Settings updated.');
      case 'time_warning':
        return text(`${ev.minutes_left} minutes left.`);
      case 'end':
        return text('You ended the session; the teacher is wrapping up…');
      case 'idle':
        return text(`No activity for ${Math.round(ev.idle_s / 60)} minutes.`);
      case 'ended':
        return text('The session has ended.');
      default:
        return null;
    }
  }
}
