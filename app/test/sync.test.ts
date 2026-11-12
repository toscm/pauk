// Progress on several devices: per-device log folders, and syncing the
// progress folder through git (two clones of a local bare repository).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { loadKnowledge } from '../src/knowledge.ts';
import { Log } from '../src/log.ts';
import { apiDir, deviceName, loadConfig } from '../src/config.ts';
import { Learner } from '../src/session.ts';
import { Sync } from '../src/sync.ts';

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'pauk-'));
const git = (cwd: string, ...args: string[]) => execFileSync('git', args, { cwd, encoding: 'utf8' }).trim();
const DECK = 'space: it\nitems:\n  - {key: essere, label: essere}\n  - {key: avere, label: avere}\n';

test('device names are folder-safe', () => {
  assert.equal(deviceName('Tobis-MacBook-Pro.local'), 'tobis-macbook-pro');
  assert.equal(deviceName('WORKSTATION01'), 'workstation01');
  assert.equal(deviceName('my laptop!'), 'my-laptop');
});

test('the log: each device appends to its own folder, all devices and old logs are read in time order', () => {
  const dir = tmp();
  const src = tmp();
  fs.writeFileSync(path.join(src, 'it.yaml'), DECK);
  const k = loadKnowledge([src]);
  fs.mkdirSync(path.join(dir, 'log', 'mac'), { recursive: true });
  const line = (t: string, item: string) => JSON.stringify({ id: t, t, type: 'answer', mode: 'recall', items: { [item]: 'good' } }) + '\n';
  fs.writeFileSync(path.join(dir, 'log', '2026-10.jsonl'), line('2026-10-01T10:00:00.000Z', 'it/essere'));   // before devices
  fs.writeFileSync(path.join(dir, 'log', 'mac', '2026-11.jsonl'), line('2026-11-02T10:00:00.000Z', 'it/avere'));
  const log = new Log(dir, 'pc');
  log.add(k, { type: 'answer', mode: 'recall', items: { 'it/essere': 'good' } });
  assert.deepEqual(fs.readdirSync(path.join(dir, 'log', 'pc')), [`${new Date().toISOString().slice(0, 7)}.jsonl`]);
  const again = new Log(dir, 'pc').replay(k);
  assert.equal(again.lines.length, 3);
  assert.deepEqual(again.lines.map((l) => l.t), [...again.lines.map((l) => l.t)].sort());
  assert.equal(again.states.get('it/essere')!.reps, 2);
  assert.equal(again.states.get('it/avere')!.reps, 1);
});

test('API logs move out of the user folder into the pauk home', () => {
  const home = tmp();
  fs.writeFileSync(path.join(home, 'config.yaml'), 'sources: []\nusers: {}\n');
  const config = loadConfig(home);
  const old = path.join(config.progress, 'tobi', 'api');
  fs.mkdirSync(old, { recursive: true });
  fs.writeFileSync(path.join(old, '2026-11.jsonl'), '{"cost":1}\n');
  new Learner('tobi', path.join(config.progress, 'tobi'), config);
  assert.ok(!fs.existsSync(old));
  assert.equal(fs.readFileSync(path.join(apiDir('tobi', home), '2026-11.jsonl'), 'utf8'), '{"cost":1}\n');
});

test('config: progress and device', () => {
  const home = tmp();
  fs.writeFileSync(path.join(home, 'config.yaml'), 'progress: ~/pauk-progress-x\ndevice: Work PC\n');
  const config = loadConfig(home);
  assert.equal(config.progress, path.join(os.homedir(), 'pauk-progress-x'));
  assert.equal(config.device, 'work-pc');
  fs.writeFileSync(path.join(home, 'config.yaml'), 'users: {}\n');
  assert.equal(loadConfig(home).progress, path.join(home, 'users'));
});

test('sync: two devices share their progress through a git remote without conflicts', async () => {
  const root = tmp();
  const remote = path.join(root, 'remote.git');
  execFileSync('git', ['init', '--quiet', '--bare', '--initial-branch=main', remote]);
  const clone = (name: string) => {
    execFileSync('git', ['clone', '--quiet', remote, name], { cwd: root, stdio: 'ignore' });   // empty: no upstream yet
    return path.join(root, name);
  };
  const a = clone('a');
  const b = clone('b');
  const write = (dir: string, file: string, text: string, append = true) => {
    fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
    (append ? fs.appendFileSync : fs.writeFileSync)(path.join(dir, file), text);
  };

  // device a starts: its first sync creates the branch on the remote
  write(a, 'tobi/log/a/2026-11.jsonl', '{"t":"1"}\n');
  write(a, 'tobi/reports.jsonl', '{"r":"a"}\n');
  write(a, 'tobi/settings.yaml', 'language: en\n', false);
  const syncA = new Sync(a, 'a');
  const r1 = await syncA.run('session 1');
  assert.equal(r1.error, undefined);
  assert.deepEqual([r1.committed, r1.pushed, r1.remote], [true, true, 'origin/main']);
  assert.ok(fs.existsSync(path.join(a, '.gitattributes')));

  // device b (its clone was made while the remote was empty) practises too
  const syncB = new Sync(b, 'b');
  git(b, 'pull', '--quiet', 'origin', 'main');
  git(b, 'branch', '--quiet', '--set-upstream-to=origin/main');
  write(b, 'tobi/log/b/2026-11.jsonl', '{"t":"2"}\n');
  write(b, 'tobi/reports.jsonl', '{"r":"b"}\n');
  write(b, 'tobi/settings.yaml', 'language: de\n', false);
  // ...while a practises again and changes the same files
  write(a, 'tobi/log/a/2026-11.jsonl', '{"t":"3"}\n');
  write(a, 'tobi/reports.jsonl', '{"r":"a2"}\n');
  write(a, 'tobi/settings.yaml', 'language: it\n', false);
  assert.equal((await syncA.run('session 2')).error, undefined);

  const r2 = await syncB.run('session 3');
  assert.equal(r2.error, undefined);
  assert.deepEqual([r2.committed, r2.pulled, r2.pushed], [true, true, true]);
  const r3 = await syncA.run('periodic');
  assert.deepEqual([r3.committed, r3.pulled, r3.pushed, r3.error], [false, true, false, undefined]);

  // both devices now have both logs; appended files kept both sides' lines;
  // for settings.yaml the device that synced last (b) won
  for (const dir of [a, b]) {
    assert.equal(fs.readFileSync(path.join(dir, 'tobi/log/a/2026-11.jsonl'), 'utf8'), '{"t":"1"}\n{"t":"3"}\n');
    assert.equal(fs.readFileSync(path.join(dir, 'tobi/log/b/2026-11.jsonl'), 'utf8'), '{"t":"2"}\n');
    assert.deepEqual(fs.readFileSync(path.join(dir, 'tobi/reports.jsonl'), 'utf8').trim().split('\n').sort(), ['{"r":"a"}', '{"r":"a2"}', '{"r":"b"}']);
    assert.equal(fs.readFileSync(path.join(dir, 'tobi/settings.yaml'), 'utf8'), 'language: de\n');
    assert.equal(git(dir, 'status', '--porcelain'), '');
  }
});

test('sync: a folder that is not a git repository is left alone; without a remote pauk only commits', async () => {
  const plain = tmp();
  assert.equal(new Sync(plain, 'x').enabled, false);
  assert.deepEqual(await new Sync(plain, 'x').run('test'), { committed: false, pulled: false, pushed: false, remote: null });
  assert.ok(!fs.existsSync(path.join(plain, '.gitattributes')));

  const local = tmp();
  git(local, 'init', '--quiet');
  fs.writeFileSync(path.join(local, 'x.jsonl'), '{}\n');
  const r = await new Sync(local, 'x').run('test');
  assert.deepEqual([r.committed, r.pushed, r.remote, r.error], [true, false, null, undefined]);
  assert.equal(git(local, 'status', '--porcelain'), '');
});
