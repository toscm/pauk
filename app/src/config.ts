// The two files in the pauk home (default ~/pauk, or $PAUK_HOME):
//
// - config.yaml: sources, teacher settings, where the progress lives.
//   It holds nothing secret, so it can be shown, shared, and kept in a
//   (dotfiles) repository and linked on every machine.
// - secrets.yaml: the API key and the users' logins of this machine.
//   Never shared; pauk creates it with a placeholder key.

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
  listen: string;     // host:port; 0.0.0.0:8642 to serve the LAN
  sources: string[];
  teacher: { model: string; effort: 'low' | 'medium' | 'high' | 'xhigh' | 'max'; debug: boolean };
  prices: Record<string, [number, number, number, number]>;   // USD per MTok: input, output, cache read, cache write
  progress: string;   // one folder per user (learning log, settings, ...); synced when it is a git repo (src/sync.ts)
  device: string;     // this machine's name: its log lines go to log/<device>/
  users: Record<string, User>;   // from secrets.yaml
  apiKey: string | null;         // from secrets.yaml; null while it is the placeholder
}

export const HOME = process.env.PAUK_HOME ?? path.join(os.homedir(), 'pauk');
const BUILTIN = path.join(import.meta.dirname, '..', 'knowledge');
const EXAMPLES = path.join(import.meta.dirname, '..', '..', 'examples');   // small decks to try pauk with

const TEMPLATE = `# pauk configuration (docs/files.md). Edit freely; restart pauk afterwards.
# Nothing secret goes here (that is secrets.yaml), so this file can be shared between machines.
format: 1
listen: 127.0.0.1:8642        # 0.0.0.0:8642 serves every device in your LAN
sources:                      # knowledge folders, read in this order; replace the examples with your own
  - ${EXAMPLES}
teacher:
  model: claude-opus-5-5      # or claude-sonnet-5-5 (cheaper), claude-haiku-5-5 (cheapest)
  effort: medium              # low | medium | high | xhigh | max
  debug: true                 # write every API request and response to api/<name>/
prices:                       # USD per million tokens: input, output, cache read, cache write (check anthropic.com/pricing)
  claude-opus-5-5: [4, 20, 0.2, 5]
  claude-sonnet-5-5: [2, 10, 0.2, 2.5]
  claude-haiku-5-5: [0.1, 0.5, 0.01, 0.125]
# progress: ~/repos/pauk-progress   # where the users' learning data lives (default: users/ here);
#                                   # a git repository is synced (docs/files.md)
# device: laptop                    # this machine's name in the log (default: the host name)
`;

const PLACEHOLDER = 'sk-ant-REPLACE-ME';
const SECRETS = `# pauk's secrets on this machine (docs/files.md). Never commit, copy or share this file.
# Claude API key for the teacher, from https://platform.claude.com -> Settings -> API keys
# (ANTHROPIC_API_KEY set in the shell wins over this one).
anthropic_api_key: ${PLACEHOLDER}
# Logins, written by: pauk user add NAME [--admin] [--llm] [--budget USD]
users: {}
`;

export function configPath(home = HOME): string {
  return path.join(home, 'config.yaml');
}

export function secretsPath(home = HOME): string {
  return path.join(home, 'secrets.yaml');
}

export function loadConfig(home = HOME): Config {
  const file = configPath(home);
  if (!fs.existsSync(file)) {
    fs.mkdirSync(home, { recursive: true });
    fs.writeFileSync(file, TEMPLATE);
  }
  if (!fs.existsSync(secretsPath(home))) fs.writeFileSync(secretsPath(home), SECRETS, { mode: 0o600 });
  migrateSecrets(home);
  const c = YAML.parse(fs.readFileSync(file, 'utf8')) ?? {};
  const secrets = YAML.parse(fs.readFileSync(secretsPath(home), 'utf8')) ?? {};
  const expand = (p: string) => path.resolve(home, p.replace(/^~(?=$|[\\/])/, os.homedir()));
  const key = String(secrets.anthropic_api_key ?? '').trim();
  return {
    home,
    listen: c.listen ?? '127.0.0.1:8642',
    sources: [BUILTIN, ...(c.sources ?? []).map(expand)],
    teacher: { model: 'claude-opus-5-5', effort: 'medium', debug: true, ...c.teacher },
    prices: c.prices ?? {},
    progress: c.progress ? expand(String(c.progress)) : path.join(home, 'users'),
    device: deviceName(c.device),
    users: secrets.users ?? {},
    apiKey: key && !key.includes('REPLACE-ME') ? key : null,
  };
}

// Earlier versions kept the users in config.yaml and the API key in .env;
// both move into secrets.yaml (once, on the first start after the update).
function migrateSecrets(home: string): void {
  const configDoc = YAML.parseDocument(fs.readFileSync(configPath(home), 'utf8'));
  const oldUsers = configDoc.get('users');
  const envFile = path.join(home, '.env');
  if (!configDoc.has('users') && !fs.existsSync(envFile)) return;
  const secrets = YAML.parseDocument(fs.readFileSync(secretsPath(home), 'utf8'));
  if (YAML.isMap(oldUsers)) {
    for (const pair of oldUsers.items) {
      const name = String(YAML.isScalar(pair.key) ? pair.key.value : pair.key);
      if (!secrets.hasIn(['users', name])) secrets.setIn(['users', name], pair.value);
    }
    blockStyle(secrets);
  }
  if (configDoc.has('users')) {
    configDoc.delete('users');
    fs.writeFileSync(configPath(home), configDoc.toString());
  }
  if (fs.existsSync(envFile)) {
    const m = /^\s*ANTHROPIC_API_KEY\s*=\s*["']?([^"'\s#]+)/m.exec(fs.readFileSync(envFile, 'utf8'));
    const current = String(secrets.get('anthropic_api_key') ?? '');
    if (m && !m[1].includes('REPLACE-ME') && (!current || current.includes('REPLACE-ME'))) secrets.set('anthropic_api_key', m[1]);
    fs.rmSync(envFile);
  }
  fs.writeFileSync(secretsPath(home), secrets.toString(), { mode: 0o600 });
  console.log(`moved the users and the API key into ${secretsPath(home)} (config.yaml holds nothing secret now)`);
}

// users in block style, one field per line
function blockStyle(doc: YAML.Document): void {
  const users = doc.get('users', true);
  if (YAML.isNode(users)) YAML.visit(users, { Map: (_, m) => void (m.flow = false) });
}

// A folder-safe device name: "Tobis-MacBook-Pro.local" -> "tobis-macbook-pro".
export function deviceName(name: unknown = os.hostname()): string {
  const s = String(name ?? os.hostname()).toLowerCase().replace(/\.(local|lan|home)$/, '');
  return s.replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '') || 'device';
}

// Add or update a user in secrets.yaml, keeping the file's comments.
export function setUser(name: string, fields: Partial<User>, home = HOME): void {
  loadConfig(home);   // creates the files on first use
  const doc = YAML.parseDocument(fs.readFileSync(secretsPath(home), 'utf8'));
  if (!doc.has('users') || !YAML.isMap(doc.get('users'))) doc.set('users', doc.createNode({}));
  for (const [k, v] of Object.entries(fields)) doc.setIn(['users', name, k], v);
  blockStyle(doc);
  fs.writeFileSync(secretsPath(home), doc.toString(), { mode: 0o600 });
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

// A user's learning data, in the progress folder.
export function userDir(name: string, progress = path.join(HOME, 'users')): string {
  const dir = path.join(progress, name);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

// A user's API call log. It stays in the pauk home, outside the progress
// folder: it is large (full requests with teacher.debug) and per machine.
export function apiDir(name: string, home = HOME): string {
  return path.join(home, 'api', name);
}

export interface Settings { language: 'en' | 'de'; new_items: number; favorites: string[] }

export function loadSettings(dir: string): Settings {
  const file = path.join(dir, 'settings.yaml');
  const s = fs.existsSync(file) ? YAML.parse(fs.readFileSync(file, 'utf8')) ?? {} : {};
  return { language: 'en', new_items: 8, favorites: [], ...s };
}
