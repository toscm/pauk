// The chat transcript: renders every learner-visible event type,
// dedupes by seq, routes updates to exercise widgets and proposal
// cards, and tracks what the status line needs. Tasks (exercises,
// drills, activities) stay in the chat where they arrive; the side
// panel lists them so an older one is one click away.

import { activityCard } from './activity.js';
import { ProposalCard, itemCard, summaryCard } from './cards.js';
import { Drill, ExerciseWidget } from './exercises.js';
import { t } from './i18n.js';
import { md, plain } from './md.js';
import { goalText } from './start.js';
import { arrow, h } from './ui.js';

// Learner events after which the teacher is expected to respond.
const AWAITS_TEACHER = new Set(['learner_message', 'start', 'hint_request', 'explain_request', 'end']);

const short = (text, n = 60) => (text.length > n ? `${text.slice(0, n - 1).trimEnd()}…` : text);

export class Transcript {
  constructor(container, {list, onReport, onChange}) {
    this.container = container;
    this.list = list;
    this.onReport = onReport;
    this.onChange = onChange;
    this.seen = new Set();
    this.events = [];              // everything shown so far, for rebuild()
    this.widgets = new Map();      // exercise_id -> ExerciseWidget
    this.proposals = new Map();    // proposal_id -> ProposalCard
    this.activities = new Map();   // aid -> activity card
    this.tasks = [];               // {n, seq, title, el, done()} in order of arrival
    this.shown = null;             // the task last jumped to from the side panel
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
    this.tasks = [];
    this.shown = null;
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
    const tasks = this.tasks.length;
    const node = this.render(ev, live);
    if (node) {
      const entry = h('article', {class: `entry from-${ev.from} type-${ev.type}`, 'data-seq': ev.seq},
        node,
        h('button', {type: 'button', class: 'flag', title: t('transcript.flag'),
                     'aria-label': t('transcript.flag_entry', {seq: ev.seq}), onclick: () => this.onReport(ev.seq)}, '⚑'));
      this.container.append(entry);
      if (live) this.scrollToEnd('smooth');
    }
    if (live && this.tasks.length > tasks) this.focusTask(this.tasks.at(-1));
    this.renderTasks();
    this.onChange(ev, live);
  }

  // The scroller scrolls on wide screens, the page on narrow ones.
  scrollToEnd(behavior = 'auto') {
    this.container.lastElementChild?.scrollIntoView({block: 'end', behavior});
  }

  // --- tasks ------------------------------------------------------------

  // A task is rendered in the chat like any entry and listed in the
  // side panel.
  addTask(ev, el, title, done) {
    this.tasks.push({n: this.tasks.length + 1, seq: ev.seq, title: short(title), el, done});
    return el;
  }

  // Jump to a task from the side panel: scroll it into view and mark it
  // briefly.
  show(task) {
    this.shown = task;
    const entry = task.el.closest('.entry') || task.el;
    entry.scrollIntoView({block: 'start', behavior: 'smooth'});
    entry.classList.remove('flash');
    void entry.offsetWidth;   // restart the animation
    entry.classList.add('flash');
    this.focusTask(task);
    this.renderTasks();
  }

  focusTask(task) {
    const exercise = task.el.matches('.exercise') ? task.el : task.el.querySelector('.exercise');
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
                     onclick: () => this.show(task)},
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
                            () => drill.current() >= drill.widgets.length);
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
      case 'explain_request':
        widget?.explainRequested();
        return null;
      case 'explanation':
        widget?.explained();
        return h('div', {class: 'bubble teacher explanation'},
          h('p', {class: 'muted small'}, t('ex.explanation_of', {prompt: short(plain(ev.prompt_md || ''), 80)})), md(ev.text_md));
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
