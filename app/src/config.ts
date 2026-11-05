// config.yaml in the pauk home (default ~/pauk, or $PAUK_HOME): sources,
// users, teacher settings. The API key is never stored here; the SDK
// reads ANTHROPIC_API_KEY from the environment.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import YAML from 'yaml';

export interface User {
  password: string;   // scrypt$salt$hash
  admin?: boolean;
  llm?: boolean;      // may use the Claude teacher
  budget?: number;    // USD per calendar month for the teacher; none means no limit
}

export interface Config {
  home: string;
  listen: string;     // host:port; 0.0.0.0:8765 to serve the LAN
  sources: string[];
  teacher: { model: string; effort: 'low' | 'medium' | 'high' | 'xhigh' | 'max'; debug: boolean };
  prices: Record<string, [number, number, number, number]>;   // USD per MTok: input, output, cache read, cache write
  users: Record<string, User>;
}

export const HOME = process.env.PAUK_HOME ?? path.join(os.homedir(), 'pauk');
const BUILTIN = path.join(import.meta.dirname, '..', 'knowledge');
const EXAMPLES = path.join(import.meta.dirname, '..', '..', 'examples');   // small decks to try pauk with

const TEMPLATE = `# pauk configuration (docs/files.md). Edit freely; restart pauk afterwards.
format: 1
listen: 127.0.0.1:8765        # 0.0.0.0:8765 serves every device in your LAN
sources:                      # knowledge folders, read in this order; replace the examples with your own
  - ${EXAMPLES}
teacher:
  model: claude-opus-5-5      # or claude-sonnet-5-5 (cheaper), claude-haiku-5-5 (cheapest)
  effort: medium              # low | medium | high | xhigh | max
  debug: true                 # write every API request and response to users/<name>/api/
prices:                       # USD per million tokens: input, output, cache read, cache write (check anthropic.com/pricing)
  claude-opus-5-5: [4, 20, 0.2, 5]
  claude-sonnet-5-5: [2, 10, 0.2, 2.5]
  claude-haiku-5-5: [0.1, 0.5, 0.01, 0.125]
users: {}                     # pauk user add NAME
`;

export function configPath(home = HOME): string {
  return path.join(home, 'config.yaml');
}

export function loadConfig(home = HOME): Config {
  const file = configPath(home);
  if (!fs.existsSync(file)) {
    fs.mkdirSync(home, { recursive: true });
    fs.writeFileSync(file, TEMPLATE, { mode: 0o600 });   // it holds password hashes
  }
  const c = YAML.parse(fs.readFileSync(file, 'utf8')) ?? {};
  const expand = (p: string) => path.resolve(home, p.replace(/^~(?=$|\/)/, os.homedir()));
  return {
    home,
    listen: c.listen ?? '127.0.0.1:8765',
    sources: [BUILTIN, ...(c.sources ?? []).map(expand)],
    teacher: { model: 'claude-opus-5-5', effort: 'medium', debug: true, ...c.teacher },
    prices: c.prices ?? {},
    users: c.users ?? {},
  };
}

// Add or update a user in config.yaml, keeping the file's comments.
export function setUser(name: string, fields: Partial<User>, home = HOME): void {
  loadConfig(home);   // creates the file on first use
  const doc = YAML.parseDocument(fs.readFileSync(configPath(home), 'utf8'));
  if (!doc.has('users') || !YAML.isMap(doc.get('users'))) doc.set('users', doc.createNode({}));
  for (const [k, v] of Object.entries(fields)) doc.setIn(['users', name, k], v);
  YAML.visit(doc.get('users', true) as YAML.Node, { Map: (_, m) => void (m.flow = false) });   // block style, one field per line
  fs.writeFileSync(configPath(home), doc.toString());
}

export function hashPassword(pw: string): string {
  const salt = crypto.randomBytes(16).toString('hex');
  return `scrypt$${salt}$${crypto.scryptSync(pw, salt, 32).toString('hex')}`;
}

export function checkPassword(pw: string, stored: string): boolean {
  const [, salt, hash] = stored.split('$');
  if (!salt || !hash) return false;
  return crypto.timingSafeEqual(crypto.scryptSync(pw, salt, 32), Buffer.from(hash, 'hex'));
}

export function userDir(name: string, home = HOME): string {
  const dir = path.join(home, 'users', name);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

export interface Settings { language: 'en' | 'de'; new_items: number; favorites: string[] }

export function loadSettings(dir: string): Settings {
  const file = path.join(dir, 'settings.yaml');
  const s = fs.existsSync(file) ? YAML.parse(fs.readFileSync(file, 'utf8')) ?? {} : {};
  return { language: 'en', new_items: 8, favorites: [], ...s };
}
