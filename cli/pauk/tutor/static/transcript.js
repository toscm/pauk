// The chat transcript: renders every learner-visible event type,
// dedupes by seq, routes updates to exercise widgets and proposal
// cards, and tracks what the status line needs. Tasks (exercises,
// drills, activities) do not go into the chat: the task pane above it
// shows one at a time, the newest by default, and the side panel lists
// all of them so older ones can be shown again.

import { activityCard } from './activity.js';
import { ProposalCard, itemCard, summaryCard } from './cards.js';
import { Drill, ExerciseWidget } from './exercises.js';
import { t } from './i18n.js';
import { md, plain } from './md.js';
import { goalText } from './start.js';
import { arrow, h } from './ui.js';

// Learner events after which the teacher is expected to respond.
const AWAITS_TEACHER = new Set(['learner_message', 'start', 'hint_request', 'end']);

const short = (text, n = 60) => (text.length > n ? `${text.slice(0, n - 1).trimEnd()}…` : text);

export class Transcript {
  constructor(container, {pane, list, onReport, onChange}) {
    this.container = container;
    this.scroller = container.closest('.scroller') || container;
    this.pane = pane;
    this.list = list;
    this.onReport = onReport;
    this.onChange = onChange;
    this.seen = new Set();
    this.events = [];              // everything shown so far, for rebuild()
    this.widgets = new Map();      // exercise_id -> ExerciseWidget
    this.proposals = new Map();    // proposal_id -> ProposalCard
    this.activities = new Map();   // aid -> activity card
    this.tasks = [];               // {n, seq, title, el, done()} in order of arrival
    this.shown = null;             // the task in the pane
    this.teacherSeen = false;      // any teacher event so far
    this.awaiting = false;         // the learner acted, the teacher has not answered yet
    this.ended = false;
  }

  // Render every event again (after a UI language change), keeping
  // what the learner has typed into open exercises.
  rebuild() {
    const typed = new Map([...this.widgets].filter(([, w]) => w.input && !w.locked).map(([id, w]) => [id, w.input.value]));
    const events = this.events;
    const shown = this.shown?.n;
    this.seen = new Set();
    this.events = [];
    this.widgets = new Map();
    this.proposals = new Map();
    this.activities = new Map();
    this.tasks = [];
    this.shown = null;
    this.teacherSeen = false;
    this.awaiting = false;
    this.ended = false;
    this.container.replaceChildren();
    for (const ev of events) this.add(ev, false);
    if (shown && this.tasks[shown - 1]) this.show(this.tasks[shown - 1]);
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
      if (live) this.scrollToEnd('smooth');
    }
    if (live && this.shown?.seq === ev.seq) this.focusTask();
    this.renderTasks();
    this.onChange(ev, live);
  }

  scrollToEnd(behavior = 'auto') {
    this.scroller.scrollTo({top: this.scroller.scrollHeight, behavior});
  }

  // --- tasks ------------------------------------------------------------

  // A new task goes to the pane (replacing whatever was shown there);
  // the chat keeps a one-line link to it.
  addTask(ev, el, title, done) {
    const task = {n: this.tasks.length + 1, seq: ev.seq, title: short(title), el, done};
    this.tasks.push(task);
    this.show(task);
    return h('p', {class: 'notice'},
      h('button', {type: 'button', class: 'link task-link', onclick: () => this.show(task, true)},
        t('task.link', {n: task.n, title: task.title})));
  }

  show(task, focus = false) {
    this.shown = task;
    const latest = this.tasks.at(-1);
    const older = task !== latest;
    this.pane.replaceChildren(
      h('header', {class: 'task-head'},
        h('strong', {}, t('task.number', {n: task.n})),
        older ? h('span', {class: 'muted small'}, t('task.older', {total: this.tasks.length})) : null,
        older ? h('button', {type: 'button', class: 'small', onclick: () => this.show(latest, true)}, t('task.back')) : null,
        h('button', {type: 'button', class: 'flag', title: t('transcript.flag'),
                     'aria-label': t('transcript.flag_entry', {seq: task.seq}), onclick: () => this.onReport(task.seq)}, '⚑')),
      task.el);
    this.pane.hidden = false;
    this.pane.classList.toggle('wide', task.el.classList.contains('wide'));
    this.pane.scrollTop = 0;
    if (focus) this.focusTask();
    this.renderTasks();
  }

  focusTask() {
    const exercise = this.shown?.el.matches('.exercise') ? this.shown.el : this.shown?.el.querySelector('.exercise');
    exercise?.querySelector('input:not(:disabled), textarea:not(:disabled), select:not(:disabled), button:not(:disabled)')
      ?.focus({preventScroll: true});
  }

  renderTasks() {
    if (!this.list) return;
    if (!this.tasks.length) {
      this.list.replaceChildren(h('p', {class: 'small muted'}, t('task.none')));
      return;
    }
    this.list.replaceChildren(h('ol', {class: 'task-list'}, this.tasks.map((task) => {
      const open = !task.done();
      return h('li', {class: open ? 'open' : 'done'},
        h('button', {type: 'button', class: 'link', 'aria-current': task === this.shown ? 'true' : null,
                     onclick: () => this.show(task, true)},
          h('span', {class: 'n'}, `${task.n}.`), h('span', {}, task.title, open ? h('span', {class: 'open-dot', title: t('task.open'), 'aria-label': t('task.open')}, ' ●') : null)));
    })));
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
      case 'exercise': {
        const w = this.register(new ExerciseWidget(ev));
        return this.addTask(ev, w.el, plain(ev.prompt_md), () => w.locked);
      }
      case 'drill': {
        const drill = new Drill(ev, (w) => this.register(w));
        return this.addTask(ev, drill.el, t('task.drill', {count: ev.exercises.length}),
                            () => drill.index >= drill.widgets.length);
      }
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
        return this.addTask(ev, card.el, ev.view?.title || card.el.getAttribute('aria-label') || t('activity.activity'),
                            () => !!card.finished);
      }
      case 'activity_update':
        this.activities.get(ev.aid)?.update(ev);
        return null;
      case 'activity_done': {
        const card = this.activities.get(ev.aid);
        if (card) card.finished = true;
        card?.done(ev);
        return null;
      }
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
