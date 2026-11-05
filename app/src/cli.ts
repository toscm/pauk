#!/usr/bin/env -S node --disable-warning=ExperimentalWarning
// pauk start | check | user add | debug | service | restart  (pauk help)

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline/promises';
import { parseArgs } from 'node:util';
import { configPath, HOME, hashPassword, loadConfig, setUser, userDir } from './config.ts';
import { loadKnowledge } from './knowledge.ts';
import { serve } from './server.ts';
import { restart, service } from './service.ts';

const HELP = `pauk — knowledge in text files, an LLM teacher, a local web app

  pauk start                      serve the app (address from config.yaml)
  pauk check                      validate all knowledge files (file:line)
  pauk user add NAME [--admin] [--llm] [--budget USD]
                                  add a user or change their password
  pauk debug [--user NAME] [--session ID] [--call N]
                                  what was sent to the Claude API, and what it cost
  pauk service install | uninstall
                                  macOS: run pauk at login (launchd) with a menu bar item
  pauk restart                    restart that service (or press Ctrl+Option+Cmd+P)

Data and config.yaml live in ${configPath()} (set PAUK_HOME to move them).
Secrets such as ANTHROPIC_API_KEY can go into ${path.join(HOME, '.env')} (KEY=value lines).`;

// ~/pauk/.env: secrets for pauk only (the shell's environment wins)
if (fs.existsSync(path.join(HOME, '.env'))) process.loadEnvFile(path.join(HOME, '.env'));

const [cmd, sub, ...rest] = process.argv.slice(2);
const config = loadConfig();

if (cmd === 'start') {
  const [host, port] = config.listen.split(':');
  if (!Object.keys(config.users).length) console.log('No users yet: run `pauk user add NAME` first.');
  if (!process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_API_KEY.includes('REPLACE-ME')) console.log(`ANTHROPIC_API_KEY is not set (in the shell or ${path.join(HOME, '.env')}): practice works, the teacher does not.`);
  serve(config).listen(Number(port), host, () => {
    const addrs = host === '0.0.0.0'
      ? Object.values(os.networkInterfaces()).flat().filter((a) => a?.family === 'IPv4').map((a) => a!.address)
      : [host];
    for (const a of addrs) console.log(`pauk is running at http://${a}:${port}`);
  });
} else if (cmd === 'check') {
  const k = loadKnowledge(config.sources);
  for (const e of k.errors) console.log(`error   ${e.where}: ${e.message}`);
  for (const w of k.warnings) console.log(`warning ${w.where}: ${w.message}`);
  console.log(`${k.items.size} items, ${k.cards.size} cards, ${k.subjects.size} subjects from ${config.sources.length} sources; ${k.errors.length} errors, ${k.warnings.length} warnings`);
  process.exitCode = k.errors.length ? 1 : 0;
} else if (cmd === 'user' && sub === 'add' && rest[0]) {
  const { values: o } = parseArgs({ args: rest.slice(1), options: { admin: { type: 'boolean' }, llm: { type: 'boolean' }, budget: { type: 'string' } } });
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  const pw = await rl.question(`Password for ${rest[0]}: `);
  rl.close();
  setUser(rest[0], {
    password: hashPassword(pw),
    ...(o.admin ? { admin: true } : {}), ...(o.llm ? { llm: true } : {}), ...(o.budget ? { budget: Number(o.budget) } : {}),
  });
  console.log(`saved ${rest[0]} in ${configPath()}`);
} else if (cmd === 'service') {
  service(sub);
} else if (cmd === 'restart') {
  restart();
} else if (cmd === 'debug') {
  debug(parseArgs({ args: [sub, ...rest].filter(Boolean), options: { user: { type: 'string' }, session: { type: 'string' }, call: { type: 'string' } } }).values);
} else {
  console.log(HELP);
}

// List the API calls of a session, or show one call in full.
function debug(o: { user?: string; session?: string; call?: string }): void {
  const user = o.user ?? Object.keys(config.users)[0];
  const dir = path.join(userDir(user, config.home), 'api');
  const calls = (fs.existsSync(dir) ? fs.readdirSync(dir).sort() : [])
    .flatMap((f) => fs.readFileSync(path.join(dir, f), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)));
  const session = o.session ?? calls.at(-1)?.session;
  const mine = calls.filter((c) => c.session === session);
  if (!mine.length) return console.log(`no API calls for ${user}${session ? ` in session ${session}` : ''}`);
  if (o.call) {
    const c = mine[Number(o.call) - 1];
    if (!c?.request) return console.log('no request body (set teacher.debug: true in config.yaml)');
    console.log(`--- request ${o.call}: ${c.request.messages.length} messages, system ${c.request.system.length} chars, ${c.request.tools.length} tools`);
    console.log('--- newest message (the rest repeats earlier calls):');
    console.log(JSON.stringify(c.request.messages.at(-1), null, 2));
    console.log('--- response:');
    for (const b of c.response.content) {
      if (b.type === 'thinking') console.log(`[thinking] ${b.thinking}`);
      else if (b.type === 'text') console.log(`[text] ${b.text}`);
      else if (b.type === 'tool_use') console.log(`[tool] ${b.name} ${JSON.stringify(b.input)}`);
      else console.log(`[${b.type}]`);
    }
    return console.log('--- usage:', JSON.stringify(c.usage));
  }
  console.log(`session ${session} (${user}): pauk debug --call N shows one call\n`);
  console.log(' #  time      ms  input  cached  written  output    cost  tools');
  let total = 0;
  mine.forEach((c, i) => {
    const u = c.usage;
    const tools = (c.response?.content ?? []).filter((b: any) => b.type === 'tool_use').map((b: any) => b.name).join(' ');
    total += c.cost;
    console.log(`${String(i + 1).padStart(2)}  ${c.t.slice(11, 19)} ${String(c.ms).padStart(5)} ${String(u.input_tokens).padStart(6)} ${String(u.cache_read_input_tokens ?? 0).padStart(7)} ${String(u.cache_creation_input_tokens ?? 0).padStart(8)} ${String(u.output_tokens).padStart(7)} ${c.cost.toFixed(4).padStart(7)}  ${tools || c.stop_reason}`);
  });
  console.log(`\n${mine.length} calls, $${total.toFixed(4)} in this session, $${(mine.at(-1).spent_this_month ?? 0).toFixed(2)} this month`);
}
