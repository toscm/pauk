// A learner and one tutoring session: the event stream the browser shows,
// the open exercises, and the rules (keys stay hidden, open answers are
// graded before the next question, a budget of new items per session).

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { loadFile, loadKnowledge, type Item, type Knowledge } from './knowledge.ts';
import { Log } from './log.ts';
import { capHinted, type Outcome, OUTCOMES } from './memory.ts';
import { exerciseError, fromCard, grade, KEYED, modeOf, publicView, type Exercise } from './grader.ts';
import { next } from './profile.ts';
import { apiDir, loadSettings, type Config, type Settings } from './config.ts';

export class Learner {
  name: string;
  dir: string;
  settings: Settings;
  knowledge!: Knowledge;
  log!: Log;
  private config: Config;

  constructor(name: string, dir: string, config: Config) {
    this.name = name;
    this.dir = dir;
    this.config = config;
    this.settings = loadSettings(dir);
    moveApiLogs(path.join(dir, 'api'), apiDir(name, config.home));
    this.reload();
  }

  get ownItems(): string {
    return path.join(this.dir, 'items.yaml');
  }

  // Re-read knowledge files and replay the log (after a file changed).
  reload(): void {
    const k = loadKnowledge(this.config.sources);
    if (fs.existsSync(this.ownItems)) loadFile(k, this.dir, this.ownItems, k.media.push(this.dir) - 1, 'mine');
    this.knowledge = k;
    this.log = (this.log ?? new Log(this.dir, this.config.device)).replay(k);
  }
}

// API logs used to be kept in the user's folder; they now stay out of the
// progress folder, which may be synced (config.ts apiDir).
function moveApiLogs(from: string, to: string): void {
  if (!fs.existsSync(from)) return;
  fs.mkdirSync(to, { recursive: true });
  for (const f of fs.readdirSync(from)) {
    fs.appendFileSync(path.join(to, f), fs.readFileSync(path.join(from, f)));
    fs.rmSync(path.join(from, f));
  }
  fs.rmdirSync(from);
}

export interface Event { seq: number; t: string; type: string; [k: string]: unknown }

interface Open {
  ex: Exercise;
  state: 'open' | 'answered' | 'graded';
  hinted: boolean;
  resp?: unknown;
  line?: string;   // id of the log line that recorded the grade
}

export type Goal = { subject?: string; teacher: boolean; minutes?: number };

export class Session {
  id: string;
  learner: Learner;
  goal: Goal;
  events: Event[] = [];
  exercises = new Map<string, Open>();
  newItems = new Set<string>();
  ended = false;
  listeners = new Set<(e: Event) => void>();
  onLearner: (e: Event) => void = () => {};   // the teacher subscribes here
  onClose: () => void = () => {};             // the server syncs the progress here
  private file: string;

  constructor(learner: Learner, goal: Goal) {
    this.id = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    this.learner = learner;
    this.goal = goal;
    fs.mkdirSync(path.join(learner.dir, 'sessions'), { recursive: true });
    this.file = path.join(learner.dir, 'sessions', `${this.id}.jsonl`);
  }

  get k() { return this.learner.knowledge; }
  get openCount() { return [...this.exercises.values()].filter((o) => o.state === 'open').length; }
  get log() { return this.learner.log; }

  emit(type: string, data: Record<string, unknown> = {}): Event {
    const e: Event = { seq: this.events.length + 1, t: new Date().toISOString(), type, ...data };
    this.events.push(e);
    fs.appendFileSync(this.file, JSON.stringify(e) + '\n');
    for (const l of this.listeners) l(e);
    return e;
  }

  private learnerEvent(type: string, data: Record<string, unknown> = {}): Event {
    const e = this.emit(type, { from: 'learner', ...data });
    this.onLearner(e);
    return e;
  }

  // --- what the learner does ---------------------------------------

  start(): void {
    this.learnerEvent('start', { goal: this.goal, language: this.learner.settings.language });
    if (!this.goal.teacher) this.practiceNext();
  }

  message(text: string): void {
    this.learnerEvent('learner_message', { text });
  }

  answer(id: string, resp: Record<string, unknown>): void {
    const o = this.exercises.get(id);
    if (!o || o.state !== 'open') throw new Error('this exercise is not open');
    o.resp = resp;
    const { ex } = o;
    if (KEYED.includes(ex.kind)) {
      const g = grade(ex, resp);
      const outcome = capHinted(g.outcome, o.hinted);
      o.line = this.log.add(this.k, { type: 'answer', session: this.id, mode: modeOf(ex), grader: g.grader, ex, resp,
        items: Object.fromEntries(ex.items.map((r) => [r, outcome])) }).id;
      o.state = 'graded';
      this.learnerEvent('answered', { id, resp, match: g.match, outcome, expected: g.expected });
    } else if (ex.kind === 'recall') {
      // the learner saw the reference and judged themselves
      const outcome = OUTCOMES.includes(resp.self as Outcome) ? (resp.self as Outcome) : 'fail';
      o.line = this.log.add(this.k, { type: 'answer', session: this.id, mode: modeOf(ex), grader: 'self', ex, resp,
        items: Object.fromEntries(ex.items.map((r) => [r, capHinted(outcome, o.hinted)])) }).id;
      o.state = 'graded';
      this.learnerEvent('answered', { id, resp, outcome });
    } else {
      o.state = 'answered';
      this.learnerEvent('answered', { id, resp, waiting_for: 'teacher' });
    }
    if (!this.goal.teacher && o.state === 'graded') {
      const ok = (this.log.lines.at(-1)!.items?.[ex.items[0]] ?? 'fail') !== 'fail';
      for (const r of ex.items) this.streak.set(r, ok ? (this.streak.get(r) ?? 0) + 1 : 0);
      this.practiceNext();
    }
  }

  // A recall exercise: show the reference, then the learner grades themselves.
  reveal(id: string) {
    const o = this.exercises.get(id);
    if (!o || o.ex.kind !== 'recall' || o.state !== 'open') throw new Error('not an open recall exercise');
    this.emit('reveal', { from: 'learner', id });   // not worth waking the teacher
    return { reference: o.ex.reference };
  }

  // Explaining before answering gives the answer away: it counts as "I don't know".
  askExplain(id: string): void {
    const o = this.exercises.get(id);
    if (!o) throw new Error('no such exercise');
    const gaveUp = o.state === 'open';
    if (gaveUp && o.ex.kind === 'open') {
      o.resp = { gave_up: true };
      o.state = 'answered';   // the teacher still grades it, as fail
    } else if (gaveUp) {
      o.resp = { gave_up: true };
      o.line = this.log.add(this.k, { type: 'answer', session: this.id, mode: modeOf(o.ex), grader: 'gave_up', ex: o.ex, resp: o.resp,
        items: Object.fromEntries(o.ex.items.map((r) => [r, 'fail'])) }).id;
      o.state = 'graded';
      this.emit('answered', { from: 'learner', id, resp: o.resp, outcome: 'fail' });
    }
    this.learnerEvent('explain_request', { id, exercise: o.ex, resp: o.resp ?? null, gave_up: gaveUp });
  }

  end(): void {
    if (this.ended) return;
    this.learnerEvent('end');
    if (!this.goal.teacher) this.close('');
  }

  // --- what the teacher does (each returns what the tool reports) ---

  say(text: string) {
    this.emit('message', { from: 'teacher', text });
    return { ok: true };
  }

  introduce(ref: string) {
    const item = this.k.items.get(ref);
    if (!item) throw new Error(`unknown item ${ref}`);
    this.spendNew([ref]);
    this.log.add(this.k, { type: 'introduce', session: this.id, items: { [ref]: null } });
    this.emit('item_card', { from: 'teacher', ref, label: item.label, gloss: item.gloss, body: item.body, mnemonic: item.mnemonic, anecdote: item.anecdote });
    return { ok: true };
  }

  ask(ex: Exercise) {
    const err = exerciseError(ex);
    if (err) throw new Error(err);
    const waiting = [...this.exercises].filter(([, o]) => o.state === 'answered').map(([id]) => id);
    if (waiting.length) throw new Error(`grade the answered open exercise(s) ${waiting.join(', ')} first`);
    ex.items = ex.items.map((r) => {
      const ref = this.k.aliases.get(r) ?? r;
      if (!this.k.items.has(ref)) throw new Error(`unknown item ${r}; search for it or add it first`);
      return ref;
    });
    this.spendNew(ex.items);
    const id = `e${this.exercises.size + 1}`;
    this.exercises.set(id, { ex, state: 'open', hinted: false });
    this.emit('exercise', { from: 'teacher', id, exercise: publicView(ex) });
    return { exercise_id: id };
  }

  gradeOpen(id: string, outcomes: Record<string, Outcome | null>, feedback: string) {
    const o = this.exercises.get(id);
    if (!o || o.state !== 'answered') throw new Error(`${id} is not an answered open exercise`);
    for (const [r, v] of Object.entries(outcomes)) {
      if (!o.ex.items.includes(r)) throw new Error(`${r} is not an item of ${id}`);
      if (v !== null && !OUTCOMES.includes(v)) throw new Error(`outcome must be one of ${OUTCOMES.join(', ')} or null`);
    }
    const items = Object.fromEntries(o.ex.items.map((r) => [r, outcomes[r] == null ? null : capHinted(outcomes[r]!, o.hinted)]));
    o.line = this.log.add(this.k, { type: 'answer', session: this.id, mode: modeOf(o.ex), grader: 'teacher', ex: o.ex, resp: o.resp, items }).id;
    o.state = 'graded';
    this.emit('graded', { from: 'teacher', id, outcomes: items, feedback });
    return { ok: true };
  }

  // Correct a recorded grade: an amendment line, the original stays.
  override(id: string, outcomes: Record<string, Outcome | null>, reason: string) {
    const o = this.exercises.get(id);
    if (!o?.line) throw new Error(`${id} has no recorded grade`);
    this.log.add(this.k, { type: 'amend', of: o.line, items: outcomes, reason, session: this.id });
    this.emit('override', { from: 'teacher', id, outcomes, reason });
    return { ok: true };
  }

  hint(id: string, text: string) {
    const o = this.exercises.get(id);
    if (!o || o.state !== 'open') throw new Error(`${id} is not open`);
    o.hinted = true;
    this.emit('hint', { from: 'teacher', id, text });
    return { ok: true };
  }

  explain(id: string, text: string) {
    if (!this.exercises.has(id)) throw new Error(`no exercise ${id}`);
    this.emit('explanation', { from: 'teacher', id, text });
    return { ok: true };
  }

  close(summary: string) {
    this.ended = true;
    this.emit('ended', { from: 'teacher', summary });
    this.onClose();
    return { ok: true };
  }

  // A new item spends the session's budget once; refuse beyond it.
  private spendNew(refs: string[]): void {
    const unseen = refs.filter((r) => !this.log.states.has(r) && !this.newItems.has(r));
    if (unseen.length && this.newItems.size + unseen.length > this.learner.settings.new_items)
      throw new Error(`new_item_cap: ${this.learner.settings.new_items} new items per session; practise known items instead`);
    unseen.forEach((r) => this.newItems.add(r));
  }

  // --- practice without a teacher: pauk picks the cards itself ------

  private recent: string[] = [];                 // the last items asked
  private streak = new Map<string, number>();    // correct answers in a row, this session

  practiceNext(): void {
    // an item comes back after two others until it was right twice in a row
    const again = [...this.streak].filter(([r, n]) => n < 2 && !this.recent.slice(0, 2).includes(r)).map(([r]) => r);
    const n = next(this.k, this.log, this.goal.subject, 30);
    const candidates = [...again, ...n.review.map((v) => v.ref), ...n.new.map((v) => v.ref)]
      .map((r) => this.k.items.get(r)).filter((i) => i && i.cards.length && !this.recent.slice(0, 2).includes(i.ref)) as Item[];
    for (const item of candidates) {
      try {
        if (!this.log.states.has(item.ref)) this.introduce(item.ref);
        const card = item.cards[crypto.randomInt(item.cards.length)];
        this.ask(fromCard(card));
        this.recent = [item.ref, ...this.recent].slice(0, 3);
        return;
      } catch {
        continue;   // the new-item budget is used up; try a known item
      }
    }
    this.emit('message', { from: 'pauk', text: 'Nothing more to practise here right now. Well done!' });
  }
}
