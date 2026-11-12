// config.yaml holds nothing secret; the API key and the logins are in
// secrets.yaml, and older homes are migrated into that layout.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import YAML from 'yaml';
import { configPath, loadConfig, secretsPath, setUser } from '../src/config.ts';

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'pauk-'));

test('a new home: config.yaml without secrets, secrets.yaml with a placeholder key', () => {
  const home = tmp();
  const config = loadConfig(home);
  assert.equal(config.listen, '127.0.0.1:8642');
  assert.equal(config.apiKey, null);   // the placeholder does not count
  assert.deepEqual(config.users, {});
  assert.doesNotMatch(fs.readFileSync(configPath(home), 'utf8'), /^users:/m);
  assert.match(fs.readFileSync(secretsPath(home), 'utf8'), /^anthropic_api_key: sk-ant-REPLACE-ME$/m);
  setUser('tobi', { password: 'scrypt$a$b', admin: true }, home);
  assert.deepEqual(loadConfig(home).users, { tobi: { password: 'scrypt$a$b', admin: true } });
  assert.match(fs.readFileSync(secretsPath(home), 'utf8'), /^# pauk's secrets/);   // comments kept
});

test('an older home: users leave config.yaml and the key leaves .env, both into secrets.yaml', () => {
  const home = tmp();
  fs.writeFileSync(configPath(home), '# my comment\nlisten: 127.0.0.1:9000\nusers:\n  tobi: {password: "scrypt$x$y", admin: true, budget: 20}\n  guest: {password: "scrypt$g$h"}\nsources: []\n');
  fs.writeFileSync(path.join(home, '.env'), '# key\nANTHROPIC_API_KEY="sk-ant-real"\n');
  const config = loadConfig(home);
  assert.deepEqual(Object.keys(config.users), ['tobi', 'guest']);
  assert.equal(config.users.tobi.budget, 20);
  assert.equal(config.apiKey, 'sk-ant-real');
  assert.equal(config.listen, '127.0.0.1:9000');
  const text = fs.readFileSync(configPath(home), 'utf8');
  assert.doesNotMatch(text, /users|scrypt/);
  assert.match(text, /# my comment/);
  assert.ok(!fs.existsSync(path.join(home, '.env')));
  assert.equal(YAML.parse(fs.readFileSync(secretsPath(home), 'utf8')).users.guest.password, 'scrypt$g$h');
  assert.deepEqual(loadConfig(home).users, config.users);   // a second start changes nothing
});

test('a placeholder in .env does not overwrite a real key', () => {
  const home = tmp();
  fs.writeFileSync(configPath(home), 'format: 1\n');
  fs.writeFileSync(secretsPath(home), 'anthropic_api_key: sk-ant-mine\nusers: {}\n');
  fs.writeFileSync(path.join(home, '.env'), 'ANTHROPIC_API_KEY=sk-ant-REPLACE-ME\n');
  assert.equal(loadConfig(home).apiKey, 'sk-ant-mine');
  assert.ok(!fs.existsSync(path.join(home, '.env')));
});
