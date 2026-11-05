// The HTTP server: the browser app, a small JSON API for it, and a
// server-sent event stream per session. Plain node:http, no framework.

import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import crypto from 'node:crypto';
import { stripTypeScriptTypes } from 'node:module';
import YAML from 'yaml';
import { checkPassword, loadConfig, userDir, type Config } from './config.ts';
import { Learner, Session } from './session.ts';
import { Teacher, monthSpend } from './teacher.ts';
import { itemsIn, itemView, subjects, usage } from './profile.ts';
import { addFolder, addItem, itemSource, notEditable, updateItem } from './edit.ts';

const APP = path.join(import.meta.dirname, '..', 'public');
const MODULES = path.join(import.meta.dirname, '..', 'node_modules');
const VENDOR = ['marked', 'dompurify', 'katex'];
const TYPES: Record<string, string> = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.mjs': 'text/javascript', '.ts': 'text/javascript',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.svg': 'image/svg+xml', '.webp': 'image/webp',
  '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf',
};

export function serve(config: Config = loadConfig()): http.Server {
  const loginFile = path.join(config.home, 'logins.json');   // login cookie -> user name, survives restarts
  const tokens = new Map<string, string>(fs.existsSync(loginFile) ? Object.entries(JSON.parse(fs.readFileSync(loginFile, 'utf8'))) : []);
  const learners = new Map<string, Learner>();
  const sessions = new Map<string, Session>();   // user name -> current session
  let stale = false;

  // Knowledge files edited while pauk runs are re-read on the next request.
  for (const root of config.sources) {
    if (fs.existsSync(root)) fs.watch(root, { recursive: true }, () => (stale = true));
  }

  const learner = (name: string) => {
    if (stale) {
      learners.forEach((l) => l.reload());
      stale = false;
    }
    if (!learners.has(name)) learners.set(name, new Learner(name, userDir(name, config.home), config));
    return learners.get(name)!;
  };

  const routes: Record<string, (name: string, body: any, req: http.IncomingMessage, res: http.ServerResponse) => unknown> = {
    'GET /api/me': (name) => {
      const u = config.users[name];
      const l = learner(name);
      const k = l.knowledge;
      return { name, admin: !!u.admin, llm: !!u.llm, budget: u.budget ?? null, spent: monthSpend(l.dir), settings: l.settings,
        session: sessions.get(name)?.ended === false ? sessions.get(name)!.id : null,
        problems: u.admin ? { errors: k.errors.length, warnings: k.warnings.length } : undefined };
    },
    'GET /api/subjects': (name) => {
      const l = learner(name);
      return subjects(l.knowledge, l.log, l.settings.favorites, usage(path.join(l.dir, 'sessions')));
    },
    'GET /api/items': (name, b) => itemsIn(learner(name).knowledge, learner(name).log, String(b.subject ?? '')),
    'GET /api/item': (name, b) => {
      const l = learner(name);
      const item = l.knowledge.items.get(String(b.ref));
      if (!item) throw new HttpError(404, 'no such item');
      const { cards, history: _h, links: _l, ...view } = itemView(l.knowledge, l.log, item, true) as Record<string, any>;
      return { ...view, cards: cards.length };
    },
    // editing knowledge (admins only): src/edit.ts writes the deck files
    'GET /api/item/source': (name, b) => {
      const item = editableItem(name, b.ref);
      const locked = notEditable(config.sources, item);
      return { ref: item.ref, locked, fields: locked ? null : itemSource(item) };
    },
    'PUT /api/item': (name, b) => {
      updateItem(config.sources, editableItem(name, b.ref), b.fields ?? {});
      stale = true;
      return { ref: b.ref };
    },
    'POST /api/item': (name, b) => {
      editableItem(name);
      const ref = addItem(config.sources, learner(name).knowledge, String(b.subject ?? ''), b.fields ?? {});
      stale = true;
      return { ref };
    },
    'POST /api/folder': (name, b) => {
      editableItem(name);
      const out = addFolder(config.sources, learner(name).knowledge, String(b.parent ?? ''), String(b.name ?? ''), b.fields ?? {});
      stale = true;
      return out;
    },
    'PUT /api/favorites': (name, b) => {
      const l = learner(name);
      const p = String(b.path ?? '');
      l.settings.favorites = b.on ? [...new Set([...l.settings.favorites, p])] : l.settings.favorites.filter((f) => f !== p);
      fs.writeFileSync(path.join(l.dir, 'settings.yaml'), YAML.stringify(l.settings));
      return { favorites: l.settings.favorites };
    },
    'POST /api/session': (name, b) => {
      sessions.get(name)?.end();
      const teacher = !!b.teacher && !!config.users[name].llm;
      const s = new Session(learner(name), { subject: b.subject || undefined, teacher, minutes: b.minutes });
      if (teacher) new Teacher(s, config);
      sessions.set(name, s);
      s.start();
      return { id: s.id, teacher };
    },
    'GET /api/session/events': (name, _b, req, res) => {
      const s = sessions.get(name);
      if (!s) throw new HttpError(404, 'no session');
      const after = Number(new URL(req.url!, 'http://x').searchParams.get('after') ?? 0);
      res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store' });
      const send = (e: object) => res.write(`data: ${JSON.stringify(e)}\n\n`);
      s.events.filter((e) => e.seq > after).forEach(send);
      s.listeners.add(send);
      req.on('close', () => s.listeners.delete(send));
      return undefined;   // the stream stays open
    },
    'POST /api/session/message': (name, b) => current(name).message(String(b.text ?? '')),
    'POST /api/session/answer': (name, b) => current(name).answer(b.id, b.resp ?? {}),
    'POST /api/session/reveal': (name, b) => current(name).reveal(b.id),
    'POST /api/session/explain': (name, b) => current(name).askExplain(b.id),
    'POST /api/session/end': (name) => current(name).end(),
    'PUT /api/settings': (name, b) => {
      const l = learner(name);
      l.settings = { ...l.settings, ...pick(b, ['language', 'new_items']) };
      fs.writeFileSync(path.join(l.dir, 'settings.yaml'), YAML.stringify(l.settings));
      return l.settings;
    },
  };

  // checks that the user may edit; with a ref, the item to edit
  const editableItem = (name: string, ref?: unknown) => {
    if (!config.users[name].admin) throw new HttpError(403, 'only an admin may edit knowledge');
    if (ref === undefined) return undefined as never;
    const item = learner(name).knowledge.items.get(String(ref));
    if (!item) throw new HttpError(404, 'no such item');
    return item;
  };

  const current = (name: string) => {
    const s = sessions.get(name);
    if (!s || s.ended) throw new HttpError(409, 'no running session');
    return s;
  };

  return http.createServer(async (req, res) => {
    const url = new URL(req.url!, 'http://x');
    try {
      if (!url.pathname.startsWith('/api/')) return sendFile(res, url.pathname, config);
      const body = req.method === 'GET' ? Object.fromEntries(url.searchParams) : await readJson(req);
      if (url.pathname === '/api/login') {
        const u = config.users[body.name];
        if (!u || !checkPassword(String(body.password ?? ''), u.password)) throw new HttpError(401, 'wrong name or password');
        const token = crypto.randomBytes(24).toString('hex');
        tokens.set(token, body.name);
        fs.writeFileSync(loginFile, JSON.stringify(Object.fromEntries(tokens)), { mode: 0o600 });
        res.setHeader('set-cookie', `pauk=${token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000`);
        return json(res, 200, { ok: true });
      }
      const token = /(?:^|; )pauk=([0-9a-f]+)/.exec(req.headers.cookie ?? '')?.[1];
      const name = token ? tokens.get(token) : undefined;
      if (!name || !config.users[name]) throw new HttpError(401, 'please log in');
      const route = routes[`${req.method} ${url.pathname}`];
      if (!route) throw new HttpError(404, 'no such endpoint');
      const out = await route(name, body, req, res);
      if (!res.headersSent) json(res, 200, out ?? { ok: true });
    } catch (err) {
      const status = err instanceof HttpError ? err.status : 400;
      if (!(err instanceof HttpError)) console.error(err);
      if (!res.headersSent) json(res, status, { error: err instanceof Error ? err.message : String(err) });
    }
  });
}

class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// The app (TypeScript served as JavaScript), vendor modules, and media
// of the knowledge sources (/files/<n>/media/...).
function sendFile(res: http.ServerResponse, p: string, config: Config): void {
  let file: string | null = null;
  const m = /^\/files\/(\d+)\/(media\/.+)$/.exec(p);
  const v = /^\/vendor\/([a-z]+)\/(.+)$/.exec(p);
  if (p === '/') file = path.join(APP, 'index.html');
  else if (p.startsWith('/app/')) file = inside(APP, p.slice(5));
  else if (v && VENDOR.includes(v[1])) file = inside(path.join(MODULES, v[1]), v[2]);
  else if (m) {
    const roots = [...config.sources];   // same order as Knowledge.media; users' own folders have no media
    if (roots[Number(m[1])]) file = inside(roots[Number(m[1])], decodeURIComponent(m[2]));
  }
  if (!file || !fs.existsSync(file) || !fs.statSync(file).isFile()) return void json(res, 404, { error: 'not found' });
  const ext = path.extname(file);
  let data: string | Buffer = fs.readFileSync(file);
  if (ext === '.ts') data = stripTypeScriptTypes(data.toString('utf8'));
  res.writeHead(200, { 'content-type': TYPES[ext] ?? 'application/octet-stream', 'cache-control': 'no-cache' });
  res.end(data);
}

// A path below root, or null if `rel` tries to leave it.
function inside(root: string, rel: string): string | null {
  const full = path.resolve(root, rel);
  return full.startsWith(path.resolve(root) + path.sep) ? full : null;
}

function json(res: http.ServerResponse, status: number, data: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(data));
}

async function readJson(req: http.IncomingMessage): Promise<any> {
  let raw = '';
  for await (const chunk of req) raw += chunk;
  return raw ? JSON.parse(raw) : {};
}

function pick(o: Record<string, unknown>, keys: string[]) {
  return Object.fromEntries(keys.filter((k) => o[k] !== undefined).map((k) => [k, o[k]]));
}
