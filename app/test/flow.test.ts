// Knowledge files, the learning log and whole sessions, in a scratch
// pauk home. The teacher runs against a scripted fake API client.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadKnowledge } from '../src/knowledge.ts';
import { Log } from '../src/log.ts';
import { apiDir, loadConfig } from '../src/config.ts';
import { Learner, Session } from '../src/session.ts';
import { Teacher } from '../src/teacher.ts';
import { stateView } from '../src/profile.ts';

function scratch(files: Record<string, string>) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'pauk-'));
  const src = path.join(home, 'src');
  for (const [f, text] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(src, f)), { recursive: true });
    fs.writeFileSync(path.join(src, f), text);
  }
  fs.writeFileSync(path.join(home, 'config.yaml'),
    `sources: [${src}]\nteacher: {model: claude-opus-5-5, effort: low, debug: true}\nprices: {claude-opus-5-5: [4, 20, 0.2, 5]}\nusers: {tobi: {password: x, llm: true, budget: 1}}\n`);
  return { home, src, config: loadConfig(home) };
}

const ITALIAN = `space: it
items:
  - key: essere
    kind: word
    label: essere
    gloss: to be
    aliases: [esser]
    requires: [present-are]
    cards:
      - {type: text, q: "Italian for **to be**?", answer: [essere]}
  - key: present-are
    kind: rule
    label: present tense of -are verbs
    cards:
      - {type: mc, q: "noi parl…?", answer: [-iamo], wrong: [-amo, -iano]}
`;

test('knowledge files: subjects from paths, aliases, errors with file:line', () => {
  const { src } = scratch({
    'italian/a1.yaml': ITALIAN,
    'greek/letters.md': '---\nspace: el\nkey: alpha\nkind: symbol\nlabel: α\n---\nThe first letter.',
    'broken.yaml': 'items:\n  - key: Bad\n    kind: word\n',
  });
  const k = loadKnowledge([src]);
  assert.equal(k.items.get('it/essere')!.subjects[0], 'italian/a1');
  assert.equal(k.items.get('el/alpha')!.body, 'The first letter.');
  assert.equal(k.aliases.get('it/esser'), 'it/essere');
  assert.equal(k.items.get('it/essere')!.cards.length, 1);
  assert.deepEqual(k.errors.map((e) => e.where), ['broken.yaml:2']);
});

test('the log: replay gives the same states as live updates, amendments correct grades', () => {
  const { src, home } = scratch({ 'italian/a1.yaml': ITALIAN });
  const k = loadKnowledge([src]);
  const log = new Log(home);
  log.add(k, { type: 'answer', mode: 'recall', items: { 'it/esser': 'good' } });   // an old ref
  const wrong = log.add(k, { type: 'answer', mode: 'recall', items: { 'it/essere': 'fail' } });
  const live = structuredClone(log.states.get('it/essere'));
  assert.deepEqual(new Log(home).replay(k).states.get('it/essere'), live);
  log.add(k, { type: 'amend', of: wrong.id, items: { 'it/essere': 'good' }, reason: 'synonym' });
  assert.equal(log.states.get('it/essere')!.lapses, 0);
  assert.equal(fs.readdirSync(path.join(home, 'log')).length, 1);
});

test('practice without a teacher: cards, introductions, the new-item budget', () => {
  const { config } = scratch({ 'italian/a1.yaml': ITALIAN });
  const learner = new Learner('tobi', path.join(config.home, 'users', 'tobi'), config);
  learner.settings.new_items = 1;
  const s = new Session(learner, { subject: 'italian', teacher: false });
  s.start();
  // essere requires present-are, so the rule comes first
  const intro = s.events.find((e) => e.type === 'item_card')!;
  assert.equal(intro.ref, 'it/present-are');
  const ex = s.events.find((e) => e.type === 'exercise')!;
  assert.equal(JSON.stringify(ex).includes('correct'), false);
  s.answer(ex.id as string, { selected: ['-iamo'] });
  assert.equal(stateView(learner.log, 'it/present-are').reps, 1);
  // essere stays locked until its prerequisite is known
  assert.equal(s.events.filter((e) => e.type === 'item_card').length, 1);
});

test('the teacher: tool calls act on the session, every call is logged with its cost', async () => {
  const { config } = scratch({ 'italian/a1.yaml': ITALIAN });
  const learner = new Learner('tobi', path.join(config.home, 'users', 'tobi'), config);
  const s = new Session(learner, { subject: 'italian', teacher: true });
  const usage = { input_tokens: 1000, output_tokens: 100, cache_read_input_tokens: 5000, cache_creation_input_tokens: 0 };
  const replies = [
    { content: [{ type: 'tool_use', id: 't1', name: 'say', input: { text: 'Ciao!' } },
      { type: 'tool_use', id: 't2', name: 'ask', input: { kind: 'text', items: ['it/present-are'], prompt: 'noi parl…?', accepted: ['parliamo'] } }], stop_reason: 'tool_use' },
    { content: [{ type: 'text', text: 'waiting' }], stop_reason: 'end_turn' },
  ];
  const sent: any[] = [];
  const fake = { beta: { messages: { create: async (p: any) => {
    sent.push(structuredClone(p));
    return { model: 'claude-opus-5-5', usage, ...replies.shift()! };
  } } } } as any;
  const teacher = new Teacher(s, config, fake);
  s.start();
  await teacher.idle();
  assert.deepEqual(s.events.filter((e) => e.from === 'teacher').map((e) => e.type), ['message', 'exercise']);
  assert.equal(sent.length, 2);
  assert.equal(sent[1].messages.at(-1).content[1].tool_use_id, 't2');
  const calls = fs.readFileSync(path.join(apiDir('tobi', config.home), `${new Date().toISOString().slice(0, 7)}.jsonl`), 'utf8').trim().split('\n');
  assert.ok(!fs.existsSync(path.join(learner.dir, 'api')));   // API logs stay out of the progress folder
  assert.equal(calls.length, 2);
  assert.equal(JSON.parse(calls[0]).cost, (1000 * 4 + 100 * 20 + 5000 * 0.2) / 1e6);
});

test('extend: a later source adds body and cards to an item of an earlier one', () => {
  const pub = scratch({ 'topic/a.yaml': 'space: concepts\nitems:\n  - {key: x, label: X, gloss: an x, body: Public.}\n' });
  const priv = scratch({ 'notes/b.yaml': 'space: concepts\nitems:\n  - {key: x, extend: true, body: Private., cards: [{type: recall, q: "What is x?", answer: "an x"}]}\n  - {key: y, extend: true}\n' });
  const k = loadKnowledge([pub.src, priv.src]);
  const x = k.items.get('concepts/x')!;
  assert.equal(x.body, 'Public.\n\nPrivate.');
  assert.equal(x.cards.length, 1);
  assert.deepEqual(x.subjects, ['topic/a']);   // extending does not move the item
  assert.match(k.errors.map((e) => e.message).join(), /extend: concepts\/y is not defined/);
});

test('number prefixes order subjects without being part of them; recent sessions rank subjects', async () => {
  const { src, home } = scratch({ 'it/02-a2.yaml': 'space: it\nitems:\n  - {key: b}\n', 'it/01-a1/01-hello.yaml': 'space: it\nitems:\n  - {key: a, also: [it/a2]}\n' });
  const k = loadKnowledge([src]);
  assert.deepEqual(k.items.get('it/a')!.subjects, ['it/a1/hello', 'it/a2']);
  assert.equal(k.order.get('it/a1'), 1);
  assert.equal(k.order.get('it/a2'), 2);
  const { usage } = await import('../src/profile.ts');
  fs.mkdirSync(path.join(home, 's'));
  const day = 86400e3, now = Date.parse('2026-11-10T12:00:00Z');
  fs.writeFileSync(path.join(home, 's', '1.jsonl'), JSON.stringify({ type: 'start', t: new Date(now - 7 * day).toISOString(), goal: { subject: 'it/a1' } }) + '\n');
  fs.writeFileSync(path.join(home, 's', '2.jsonl'), JSON.stringify({ type: 'start', t: new Date(now).toISOString(), goal: { subject: 'it/a1' } }) + '\n');
  assert.equal(usage(path.join(home, 's'), now).get('it/a1')!.score, 1.5);   // a week ago counts half
});
