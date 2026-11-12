// The Claude teacher: a tool-use loop over the Messages API. The model
// sees only what the tools return, and every tool acts on one learner's
// session, so it can never read files or another user's data.
// Every request and response is written to users/<name>/api/YYYY-MM.jsonl
// (usage and cost always, full bodies with teacher.debug).

import fs from 'node:fs';
import path from 'node:path';
import Anthropic from '@anthropic-ai/sdk';
import type { BetaMessageParam, BetaTool, BetaToolResultBlockParam, BetaContentBlockParam, BetaUsage } from '@anthropic-ai/sdk/resources/beta/messages/messages';
import { apiDir, type Config } from './config.ts';
import type { Event, Session } from './session.ts';
import { appendItem } from './knowledge.ts';
import { itemView, next, search, summary } from './profile.ts';
import { norm, slug, KINDS } from './text.ts';
import type { Exercise } from './grader.ts';

const SYSTEM = fs.readFileSync(path.join(import.meta.dirname, 'prompt.md'), 'utf8');
const MAX_STEPS = 30;   // model calls per learner turn, a guard against loops

const str = (description: string) => ({ type: 'string', description });
const refs = (description: string) => ({ type: 'array', items: { type: 'string' }, description });
const outcomes = { type: 'object', additionalProperties: { enum: ['fail', 'hard', 'good', 'easy', null] }, description: 'ref -> outcome (null: no evidence)' };
const tool = (name: string, description: string, properties: Record<string, unknown>, required: string[] = []): BetaTool =>
  ({ name, description, input_schema: { type: 'object', properties, required } });

export const TOOLS: BetaTool[] = [
  tool('profile', 'Counts per mastery level and due items of a subject.', { subject: str('subject path, e.g. italian; omit for all') }),
  tool('next_items', 'Due items to review and new items to introduce, ranked.', { subject: str('subject path'), n: { type: 'integer' } }),
  tool('search_items', 'Search items by label, gloss, body and aliases.', { q: str('search text'), subject: str('subject path') }),
  tool('get_item', 'One item with state, cards, links, notes and recent history.', { ref: str('space/key') }, ['ref']),
  tool('say', 'Show a chat message to the learner (Markdown).', { text: str('message') }, ['text']),
  tool('introduce', 'Show an item as a card and record that it was introduced.', { ref: str('space/key') }, ['ref']),
  tool('ask', 'Show one exercise. Returns its exercise_id.', {
    kind: { enum: ['mc', 'text', 'match', 'open', 'recall'] },
    items: refs('refs the answer gives evidence about'),
    prompt: str('the question (Markdown)'),
    mode: { enum: ['recognize', 'recall', 'produce', 'explain'] },
    options: refs('mc: all options'), correct: refs('mc: the correct options'),
    accepted: refs('text: accepted answers'),
    pairs: { type: 'array', items: { type: 'array', items: { type: 'string' } }, description: 'match: [left, right] pairs in correct order' },
    reference: str('open/recall: the reference answer'),
  }, ['kind', 'items', 'prompt']),
  tool('grade', 'Grade an answered open exercise.', { exercise_id: str('id'), outcomes, feedback: str('shown to the learner') }, ['exercise_id', 'outcomes', 'feedback']),
  tool('hint', 'A hint for an unanswered exercise; caps its outcome at hard.', { exercise_id: str('id'), text: str('hint') }, ['exercise_id', 'text']),
  tool('explain', 'Explain the topic of an exercise, shown under it.', { exercise_id: str('id'), text: str('explanation') }, ['exercise_id', 'text']),
  tool('override', 'Correct an automatic grade (e.g. a valid synonym), with a reason.', { exercise_id: str('id'), outcomes, reason: str('why') }, ['exercise_id', 'outcomes', 'reason']),
  tool('note', 'Your memo about this learner and item, kept across sessions.', { ref: str('space/key'), text: str('what you observed') }, ['ref', 'text']),
  tool('add_item', "Add a missing item to the learner's own items.", {
    space: str('it, el, de, en or concepts'), kind: { enum: KINDS }, label: str('label'), gloss: str('short meaning'), body: str('longer explanation'),
    subject: str('subject path to file it under'), distinct_from: refs('candidates you checked that are different things'),
  }, ['space', 'kind', 'label', 'gloss']),
  tool('report', 'Report a problem with pauk or its content to the developer.', { category: { enum: ['bug', 'content', 'teacher', 'ux', 'idea'] }, text: str('what happened') }, ['category', 'text']),
  tool('end_session', 'Close the session with a summary for the learner.', { summary: str('summary') }, ['summary']),
];

type Input = Record<string, any>;

export class Teacher {
  private session: Session;
  private config: Config;
  private client: Pick<Anthropic, 'beta'>;
  private messages: BetaMessageParam[] = [];
  private pending: Event[] = [];
  private busy = false;
  private spent: number;   // USD this month, kept up to date by logCall

  // `client` is replaceable so tests can script the model's replies
  constructor(session: Session, config: Config, client: Pick<Anthropic, 'beta'> = new Anthropic()) {
    this.session = session;
    this.config = config;
    this.client = client;
    this.spent = monthSpend(apiDir(session.learner.name, config.home));
    session.onLearner = (e) => this.push(e);
  }

  // resolves when the teacher has nothing left to do (for tests)
  idle(): Promise<void> {
    return new Promise((done) => {
      const check = () => (this.busy || this.pending.length ? setTimeout(check, 5) : done());
      check();
    });
  }

  push(e: Event): void {
    this.pending.push(e);
    // during a drill, collect the answers and wake the teacher after the last one
    if (e.type === 'answered' && this.session.openCount > 0) return;
    void this.run();
  }

  // Serve learner events until none are left; one turn at a time.
  private async run(): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    try {
      while (this.pending.length && !this.session.ended) {
        this.messages.push({ role: 'user', content: this.takePending() });
        await this.turn();
      }
    } catch (err) {
      console.error(err);
      const text = err instanceof Error ? err.message : String(err);
      this.session.emit('status', { teacher: 'error', text: /authentication method/.test(text)
        ? 'The teacher has no API key: put ANTHROPIC_API_KEY=... into ~/pauk/.env (or the shell that runs `pauk start`) and restart pauk.' : text });
    } finally {
      this.busy = false;
    }
  }

  private takePending(): string {
    return this.pending.splice(0).map(({ from: _f, ...e }) => JSON.stringify(e)).join('\n');
  }

  private async turn(): Promise<void> {
    const t = this.config.teacher;
    for (let i = 0; i < MAX_STEPS; i++) {
      const budget = this.config.users[this.session.learner.name]?.budget ?? Infinity;   // no budget: no limit
      if (this.spent >= budget) {
        this.session.emit('status', { teacher: 'budget', text: `This month's teacher budget ($${budget}) is used up. Practice without a teacher still works.` });
        return;
      }
      this.session.emit('status', { teacher: 'thinking' });
      const params = {
        model: t.model,
        max_tokens: 16000,
        system: SYSTEM,
        tools: TOOLS,
        messages: this.messages,
        thinking: { type: 'adaptive' as const, display: 'summarized' as const },
        output_config: { effort: t.effort },
        cache_control: { type: 'ephemeral' as const },
        // on a safety decline, the API retries on a fallback model (not available for Haiku)
        ...(t.model.includes('haiku') ? {} : { betas: ['server-side-fallback-2026-07-01'], fallbacks: 'default' as const }),
      };
      const started = Date.now();
      const res = await this.client.beta.messages.create(params);
      this.logCall(params, res, Date.now() - started);
      this.messages.push({ role: 'assistant', content: res.content as BetaContentBlockParam[] });

      if (res.stop_reason === 'refusal') {
        this.session.emit('status', { teacher: 'error', text: 'The model declined to continue.' });
        return;
      }
      const uses = res.content.filter((b) => b.type === 'tool_use');
      if (uses.length === 0 && res.stop_reason !== 'pause_turn') break;
      const results: (BetaToolResultBlockParam | { type: 'text'; text: string })[] = uses.map((u) => this.call(u.id, u.name, u.input as Input));
      if (this.pending.length) results.push({ type: 'text', text: `New events:\n${this.takePending()}` });
      if (results.length) this.messages.push({ role: 'user', content: results });
      if (this.session.ended) break;
    }
    this.session.emit('status', { teacher: 'idle' });
  }

  private call(id: string, name: string, input: Input): BetaToolResultBlockParam {
    try {
      const out = this.execute(name, input);
      return { type: 'tool_result', tool_use_id: id, content: JSON.stringify(out) };
    } catch (err) {
      return { type: 'tool_result', tool_use_id: id, content: err instanceof Error ? err.message : String(err), is_error: true };
    }
  }

  private execute(name: string, a: Input): unknown {
    const s = this.session;
    const { knowledge: k, log } = s.learner;
    const item = (ref: string) => {
      const r = k.aliases.get(ref) ?? ref;
      if (!k.items.has(r)) throw new Error(`unknown item ${ref}`);
      return k.items.get(r)!;
    };
    switch (name) {
      case 'profile': return summary(k, log, a.subject);
      case 'next_items': return next(k, log, a.subject, a.n ?? 10);
      case 'search_items': return search(k, log, a.q, a.subject);
      case 'get_item': return itemView(k, log, item(a.ref), true);
      case 'say': return s.say(a.text);
      case 'introduce': return s.introduce(item(a.ref).ref);
      case 'ask': return s.ask(a as Exercise);
      case 'grade': return s.gradeOpen(a.exercise_id, a.outcomes, a.feedback);
      case 'hint': return s.hint(a.exercise_id, a.text);
      case 'explain': return s.explain(a.exercise_id, a.text);
      case 'override': return s.override(a.exercise_id, a.outcomes, a.reason);
      case 'note': {
        log.add(k, { type: 'note', item: item(a.ref).ref, text: a.text, session: s.id });
        return { ok: true };
      }
      case 'add_item': {
        const key = slug(a.label);
        const ref = `${a.space}/${key}`;
        const dupes = [...k.items.values()].filter((i) => i.ref === ref || (i.space === a.space && norm(i.label) === norm(a.label)))
          .filter((i) => !(a.distinct_from ?? []).includes(i.ref));
        if (dupes.some((d) => d.ref === ref)) throw new Error(`${ref} exists already; use it`);
        if (dupes.length) return { possible_duplicates: dupes.map((d) => itemView(k, log, d)) };
        appendItem(s.learner.ownItems, { space: a.space, key, kind: a.kind, label: a.label, gloss: a.gloss, body: a.body, also: a.subject ? [a.subject] : undefined });
        s.learner.reload();
        s.emit('item_added', { from: 'teacher', ref, label: a.label });
        return { ref };
      }
      case 'report': {
        fs.appendFileSync(path.join(s.learner.dir, 'reports.jsonl'), JSON.stringify({ t: new Date().toISOString(), session: s.id, ...a }) + '\n');
        return { ok: true };
      }
      case 'end_session': return s.close(a.summary);
    }
    throw new Error(`unknown tool ${name}`);
  }

  private logCall(params: object, res: Anthropic.Beta.BetaMessage, ms: number): void {
    const dir = apiDir(this.session.learner.name, this.config.home);
    fs.mkdirSync(dir, { recursive: true });
    const line = {
      t: new Date().toISOString(), session: this.session.id, model: res.model, ms, stop_reason: res.stop_reason,
      usage: res.usage, cost: cost(this.config, res.model, res.usage), spent_this_month: 0,
      ...(this.config.teacher.debug ? { request: params, response: res } : {}),
    };
    this.spent += line.cost;
    line.spent_this_month = this.spent;
    fs.appendFileSync(path.join(dir, `${line.t.slice(0, 7)}.jsonl`), JSON.stringify(line) + '\n');
  }
}

export function cost(config: Config, model: string, u: BetaUsage): number {
  const p = config.prices[model] ?? Object.entries(config.prices).find(([m]) => model.startsWith(m))?.[1];
  if (!p) return 0;
  return (u.input_tokens * p[0] + u.output_tokens * p[1] + (u.cache_read_input_tokens ?? 0) * p[2] + (u.cache_creation_input_tokens ?? 0) * p[3]) / 1e6;
}

// USD spent by one learner in the current calendar month, on this machine
// (the API logs are not synced). `dir` is the learner's apiDir.
export function monthSpend(dir: string): number {
  const file = path.join(dir, `${new Date().toISOString().slice(0, 7)}.jsonl`);
  if (!fs.existsSync(file)) return 0;
  let sum = 0;
  for (const raw of fs.readFileSync(file, 'utf8').split('\n')) if (raw) sum += JSON.parse(raw).cost ?? 0;
  return sum;
}
