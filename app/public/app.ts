// The browser app: login, the start page, and the chat with its
// exercises. Every session event arrives over one EventSource and is
// rendered by `show`; the server holds all state.

import { md } from './md.ts';

type Ev = { seq: number; type: string; from?: string; id?: string; [k: string]: any };

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const el = (tag: string, cls = '', ...children: (Node | string)[]) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  e.append(...children);
  return e;
};
const button = (label: string, onclick: () => void, cls = '') => {
  const b = el('button', cls, label) as HTMLButtonElement;
  b.type = 'button';
  b.onclick = onclick;
  return b;
};

async function api(method: string, url: string, body?: unknown): Promise<any> {
  const res = await fetch(url, { method, headers: { 'content-type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json();
  if (res.status === 401) view('login');
  if (!res.ok) throw new Error(data.error);
  return data;
}

type View = 'login' | 'browse' | 'settings' | 'chat';
const VIEWS: View[] = ['login', 'browse', 'settings', 'chat'];
function view(name: View): void {
  for (const v of VIEWS) $(v).hidden = v !== name;
  $('session-nav').hidden = name !== 'chat';
  $('tabs').hidden = $('navsearch').hidden = name === 'login' || name === 'chat';
  for (const a of document.querySelectorAll<HTMLElement>('#tabs a')) a.classList.toggle('active', a.dataset.tab === name);
}

// --- login, account and settings ---------------------------------------

$('login-form').onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target as HTMLFormElement);
  try {
    await api('POST', '/api/login', { name: f.get('name'), password: f.get('password') });
    await home();
  } catch (err) {
    $('login-error').textContent = (err as Error).message;
  }
};

let me: any;
type Subject = { path: string; items: number; due: number; by_mastery: number[]; failing: number; order: number | null; favorite: boolean; recent: number };
let subjects: Subject[] = [];

async function home(): Promise<void> {
  me = await api('GET', '/api/me');
  if (me.session) return openSession();
  subjects = await api('GET', '/api/subjects');
  $('me').textContent = `Logged in as ${me.name}` + (me.llm ? ` · teacher: $${me.spent.toFixed(2)} spent this month` + (me.budget === null ? '' : ` of $${me.budget}`) : ' · practice only')
    + (me.problems?.errors ? ` · ${me.problems.errors} errors in the knowledge files (pauk check)` : '');
  const form = $<HTMLFormElement>('settings-form');
  (form.elements.namedItem('language') as HTMLSelectElement).value = me.settings.language;
  (form.elements.namedItem('new_items') as HTMLInputElement).value = me.settings.new_items;
  route();
}

// #browse/italian/a1 or #settings: the address is the state, so the
// browser's back button walks back through the folders
function route(): void {
  if (!me) return;
  const [tab, ...rest] = location.hash.slice(1).split('/');
  if (tab === 'settings') return view('settings');
  view('browse');
  renderBrowser(decodeURIComponent(rest.join('/')));
}
window.onhashchange = route;
const go = (hash: string) => { location.hash = hash; };

$('settings-form').onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target as HTMLFormElement);
  me = await api('PUT', '/api/settings', { language: f.get('language'), new_items: Number(f.get('new_items')) }).then(() => api('GET', '/api/me'));
  $('saved').textContent = 'saved';
  setTimeout(() => ($('saved').textContent = ''), 1500);
};

const start = (subject: string, teacher: boolean) => async () => {
  await api('POST', '/api/session', { subject, teacher });
  openSession();
};
$('btn-end').onclick = () => api('POST', '/api/session/end').catch(() => home());
$('home-link').onclick = (e) => {
  e.preventDefault();
  history.replaceState(null, '', '#browse');
  q.value = '';
  home();
};

// --- shared pieces -----------------------------------------------------

const find = (p: string) => subjects.find((s) => s.path === p);   // '' is everything
const name = (p: string) => p.split('/').at(-1) || 'everything';
const known = (s: Subject) => s.by_mastery.slice(3).reduce((a, b) => a + b, 0);
const stats = (s: Subject) => `${known(s)} of ${s.items} known` + (s.due ? ` · ${s.due} due` : '');
// subfolders in learning order: numbered ones first ("01-a1"), then by name
const children = (p: string) => subjects
  .filter((s) => s.path && s.path.split('/').length === (p ? p.split('/').length + 1 : 1) && (!p || s.path.startsWith(p + '/')))
  .sort((a, b) => (a.order ?? 1e9) - (b.order ?? 1e9) || a.path.localeCompare(b.path));

// A folder in a neutral colour that fills from the bottom with the item
// colours, best first: deep green, green, light green, yellow, red; the rest
// is untouched. Every level with at least one item stays visible. A folder
// whose items are all known gets the item checkmark, in its weakest green.
let svgId = 0;
function icon(s: Subject | undefined, _folder = true): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 32 26');
  svg.setAttribute('class', 'icon');
  const shape = 'M1 5a2 2 0 0 1 2-2h8l3 3h15a2 2 0 0 1 2 2v15a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2z';
  const id = `clip${++svgId}`;
  let inner = `<clipPath id="${id}"><path d="${shape}"/></clipPath><g clip-path="url(#${id})"><rect class="f-base" width="32" height="26"/>`;
  if (s && s.items) {
    const counts: [number, number][] = [[5, s.by_mastery[5]], [4, s.by_mastery[4]], [3, s.by_mastery[3]], [2, s.by_mastery[2]], [1, s.failing]];
    let y = 25;   // the folder's bottom edge
    for (const [level, n] of counts) {
      if (!n) continue;
      const h = Math.max(2, (19 * n) / s.items);   // 19: the body below the tab
      inner += `<rect class="c${level}" x="0" y="${(y -= h).toFixed(2)}" width="32" height="${h.toFixed(2)}"/>`;
    }
  }
  inner += `</g><path class="f-line" d="${shape}"/>`;
  if (s && s.items && known(s) === s.items) {
    const weakest = [3, 4, 5].find((l) => s.by_mastery[l] > 0) ?? 5;
    inner += `<g class="badge c${weakest}"><circle cx="25" cy="19" r="6"/><path d="M22.2 19.2l2 2 3.6-3.9"/></g>`;
  }
  svg.innerHTML = inner;
  return svg;
}

function star(path: string): HTMLButtonElement {
  const s = find(path);
  const b = button(s?.favorite ? '★' : '☆', async () => {
    const on = !find(path)?.favorite;
    await api('PUT', '/api/favorites', { path, on });
    subjects.forEach((x) => { if (x.path === path) x.favorite = on; });
    b.textContent = on ? '★' : '☆';
    b.classList.toggle('on', on);
    b.title = on ? 'Remove from favorites' : 'Add to favorites';
  }, s?.favorite ? 'star on' : 'star');
  b.title = s?.favorite ? 'Remove from favorites' : 'Add to favorites';
  return b;
}

function startButtons(path: string): HTMLElement {
  const row = el('div', 'row');
  if (me.llm) row.append(button('Learn with the teacher', start(path, true)));
  row.append(button('Practise', start(path, false), me.llm ? 'secondary' : ''));
  return row;
}

// italian › 1 a1 › 2 courtesy, with the matched letters marked
function pathLabel(path: string, hits = new Set<number>()): HTMLElement {
  const box = el('span', 'path');
  if (!path) return box.append(el('span', 'seg last', 'everything')), box;
  let offset = 0;
  path.split('/').forEach((seg, n, all) => {
    if (n) box.append(el('span', 'sep', ' › '));
    const part = el('span', n === all.length - 1 ? 'seg last' : 'seg');
    const order = find(all.slice(0, n + 1).join('/'))?.order;
    if (order != null) part.append(el('span', 'num', `${order} `));
    let run = '';
    let marked = false;
    const flush = () => { if (run) part.append(marked ? el('mark', '', run) : run); run = ''; };
    [...seg].forEach((ch, i) => {
      const m = hits.has(offset + i);
      if (m !== marked) { flush(); marked = m; }
      run += ch;
    });
    flush();
    box.append(part);
    offset += seg.length + 1;
  });
  return box;
}

// --- search, always in the bar at the top -----------------------------
// Like a command palette: every word of the query must match a part of the
// subject path. Favorites and recently, often used subjects rank higher and
// are suggested before anything is typed. Picking one opens it in Browse.

let active = 0;
const q = $<HTMLInputElement>('q');

function matchWord(path: string, word: string): [number, number[]] | null {
  const p = path.toLowerCase();
  let best: [number, number[]] | null = null;
  for (let i = p.indexOf(word); i >= 0; i = p.indexOf(word, i + 1)) {
    const atStart = i === 0 || '/-_ '.includes(p[i - 1]);
    const inLast = i > p.lastIndexOf('/');
    const score = 10 + word.length + (atStart ? 6 : 0) + (inLast ? 3 : 0);
    if (!best || score > best[0]) best = [score, [...word].map((_, j) => i + j)];
  }
  if (best) return best;
  const pos: number[] = [];   // letters in order, with gaps
  for (let i = 0, j = 0; i < p.length && j < word.length; i++) if (p[i] === word[j]) pos.push(i), j++;
  if (pos.length < word.length || p.slice(pos[0], pos.at(-1)).includes('/')) return null;   // within one folder name
  return [word.length - (pos.at(-1)! - pos[0] - word.length + 1) * 0.5, pos];
}

const bonus = (s: Subject) => (s.favorite ? 15 : 0) + Math.min(s.recent, 3) * 5;

function search(query: string): { s: Subject; hits: Set<number> }[] {
  const words = query.toLowerCase().split(/[\s/>›]+/).filter(Boolean);
  if (!words.length) {
    // nothing typed yet: favorites, then what was used lately
    return subjects.filter((s) => s.favorite || s.recent > 0.01)
      .sort((a, b) => bonus(b) - bonus(a)).slice(0, 10).map((s) => ({ s, hits: new Set() }));
  }
  const out = [];
  for (const s of subjects.filter((s) => s.path)) {
    let score = 0;
    const hits = new Set<number>();
    for (const w of words) {
      const m = matchWord(s.path, w);
      if (!m) { score = -Infinity; break; }
      score += m[0];
      m[1].forEach((i) => hits.add(i));
    }
    if (score > -Infinity) out.push({ s, hits, score: score + bonus(s) - s.path.split('/').length * 0.5 - s.path.length * 0.02 });
  }
  return out.sort((a, b) => b.score - a.score || a.s.path.localeCompare(b.s.path)).slice(0, 40);
}

// The list shows only while the field has the focus: a click elsewhere or
// Esc closes it.
function renderSearch(): void {
  const open = document.activeElement === q;
  const found = open ? search(q.value.trim()) : [];
  $('results').hidden = !open || (!found.length && !q.value.trim());
  if ($('results').hidden) return;
  active = Math.min(active, Math.max(found.length - 1, 0));
  $('results').replaceChildren(...(found.length ? found.map(({ s, hits }, i) => {
    const li = el('li', i === active ? 'result active' : 'result', ...(s.favorite ? [el('span', 'fav', '★')] : []),
      pathLabel(s.path, hits), el('span', 'count muted', stats(s)));
    li.setAttribute('role', 'option');
    li.onmousemove = () => { if (active !== i) { active = i; renderSearch(); } };
    li.onmousedown = (e) => e.preventDefault();   // keep the focus in the field
    li.onclick = () => pick(s.path);
    return li;
  }) : [el('li', 'muted empty', 'No subject matches.')]));
  $('results').querySelector('.active')?.scrollIntoView({ block: 'nearest' });
}

function pick(path: string): void {
  q.value = '';
  q.blur();
  go(path ? `#browse/${path}` : '#browse');
}

q.oninput = () => { active = 0; renderSearch(); };
q.onfocus = () => renderSearch();
q.onblur = () => setTimeout(renderSearch, 0);
q.onkeydown = (e) => {
  const n = $('results').children.length;
  if (e.key === 'ArrowDown') { e.preventDefault(); active = (active + 1) % n; renderSearch(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); active = (active - 1 + n) % n; renderSearch(); }
  else if (e.key === 'Enter') { const r = search(q.value.trim())[active]; if (r) pick(r.s.path); }
  else if (e.key === 'Escape') { q.value = ''; q.blur(); }
};
// "/", Ctrl+F, Ctrl+K, Ctrl+Shift+P or F1 jump to the search field
document.addEventListener('keydown', (e) => {
  if (!me || $('navsearch').hidden) return;
  const typing = /INPUT|TEXTAREA|SELECT/.test((e.target as HTMLElement).tagName);
  if (e.key === 'F1' || ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'f' || (e.shiftKey && e.key.toLowerCase() === 'p'))) || (e.key === '/' && !typing)) {
    e.preventDefault();
    q.focus();
    q.select();
  }
});

// --- the browse page: folders in learning order -------------------------

function renderBrowser(path: string): void {
  const s = find(path) ?? find('')!;
  const crumbs = el('nav', 'crumbs');
  const parts = path.split('/').filter(Boolean);
  crumbs.append(button('everything', () => go('#browse'), 'link'));
  parts.forEach((_, i) => {
    const p = parts.slice(0, i + 1).join('/');
    crumbs.append(el('span', 'sep', ' › '), button(`${find(p)?.order != null ? find(p)!.order + ' ' : ''}${parts[i]}`, () => go(`#browse/${p}`), 'link'));
  });
  const list = el('ul', 'folders');
  if (path) list.append(row('..', parts.slice(0, -1).join('/'), undefined, true));
  for (const c of children(path)) list.append(row(name(c.path), c.path, c, true));
  list.classList.toggle('unnumbered', children(path).every((c) => c.order == null));
  if (path) crumbs.append(star(path));   // small, right after the name
  const head = el('div', 'browse-head', crumbs, el('p', 'muted', stats(s)), startButtons(path));
  $('browse').replaceChildren(head, list);
  // the items filed here are the "files" of the folder
  const folders = children(path).length > 0;
  if (!path) return void (me.admin && list.append(newRow('New folder', (r) => folderForm(path, r))));
  api('GET', `/api/items?subject=${encodeURIComponent(path)}`).then((items: ItemRow[]) => {
    if (location.hash.slice(1).split('/').slice(1).join('/') !== path) return;   // the user moved on
    for (const it of items) list.append(itemRow(it));
    if (!me.admin) return;
    // a folder holds either folders or items, so it offers one of the two
    if (folders) list.append(newRow('New folder', (r) => folderForm(path, r)));
    else if (items.length >= 12) list.append(el('li', 'folder new muted', el('span', 'num'), el('span', 'name', 'Full: a folder holds at most 12 items')));
    else list.append(newRow('New item', (r) => itemForm({}, async (fields) => {
      await api('POST', '/api/item', { subject: path, fields });
      await refresh(path);
    }, r)));
  });
}

// --- editing (admins): a form in place of the row ----------------------

type Fields = { label?: string; gloss?: string; kind?: string; body?: string; mnemonic?: string; anecdote?: string; priority?: number | null; level?: number | null };
const KINDS = ['other', 'term', 'fact', 'word', 'phrase', 'form', 'rule', 'symbol', 'paper', 'skill'];

async function refresh(path: string): Promise<void> {
  subjects = await api('GET', '/api/subjects');
  renderBrowser(path);
}

function newRow(label: string, open: (row: HTMLElement) => void): HTMLElement {
  const li = el('li', 'folder new', el('span', 'num'), el('span', 'plus', '+'), el('span', 'name', label));
  li.tabIndex = 0;
  li.onclick = () => open(li);
  li.onkeydown = (e) => { if (e.key === 'Enter') li.click(); };
  return li;
}

// The item's fields; `save` gets the changed values and may throw.
function itemForm(f: Fields, save: (fields: Fields) => Promise<void>, replace: HTMLElement, extra: HTMLElement[] = []): void {
  const form = el('form', 'item-form') as HTMLFormElement;
  const input = (name: keyof Fields, label: string, value: unknown, tag = 'input') => {
    const i = el(tag) as HTMLInputElement;
    i.name = name;
    i.value = value == null ? '' : String(value);
    if (tag === 'textarea') (i as unknown as HTMLTextAreaElement).rows = Math.min(12, Math.max(3, i.value.split('\n').length + 1));
    return el('label', '', label, i);
  };
  const kind = el('select') as HTMLSelectElement;
  kind.name = 'kind';
  kind.append(...KINDS.map((k) => el('option', '', k)));
  kind.value = f.kind ?? 'other';
  const error = el('p', 'bad');
  form.append(...extra,
    input('label', 'Label: the question, word or name (Markdown)', f.label),
    input('gloss', 'Short answer: one line', f.gloss),
    input('body', 'Body: the full answer or explanation (Markdown, optional)', f.body, 'textarea'),
    el('div', 'row', el('label', '', 'Kind', kind), input('priority', 'Priority 0–100', f.priority ?? ''), input('level', 'Level', f.level ?? '')),
    input('mnemonic', 'Memory aid (optional)', f.mnemonic),
    input('anecdote', 'Anecdote (optional)', f.anecdote, 'textarea'),
    el('div', 'row', el('button', '', 'Save'), button('Cancel', () => form.replaceWith(replace), 'secondary')), error);
  form.onsubmit = async (e) => {
    e.preventDefault();
    const data = new FormData(form);
    const fields: Fields = {};
    for (const k of ['label', 'gloss', 'body', 'mnemonic', 'anecdote', 'kind'] as const) fields[k] = String(data.get(k) ?? '');
    for (const k of ['priority', 'level'] as const) fields[k] = data.get(k) === '' ? null : Number(data.get(k));
    try {
      await save(fields);
    } catch (err) {
      error.textContent = (err as Error).message;
    }
  };
  replace.replaceWith(form);
  form.querySelector<HTMLInputElement>('input:not([type=hidden])')?.focus();
}

function folderForm(parent: string, replace: HTMLElement): void {
  const name = el('input') as HTMLInputElement;
  name.name = 'folder';
  itemForm({}, async (fields) => {
    const { subject } = await api('POST', '/api/folder', { parent, name: name.value, fields });
    subjects = await api('GET', '/api/subjects');
    go(`#browse/${subject}`);
  }, replace, [el('label', '', 'Folder name', name), el('p', 'muted', 'A folder starts with its first item:')]);
}

type ItemRow = { ref: string; name: string; mastery: number; tested: boolean; recall: number | null; due: boolean };
const LEVELS = ['unseen', 'seen', 'learning', 'known', 'solid', 'mastered'];

// An item is a circle: an empty ring until it has been tested, then filled
// with a checkmark: red (mostly wrong so far), yellow, light green, green,
// deep green (mastered). It fades as the memory fades (the model's recall
// now) and is fresh again after a review.
function itemIcon(it: ItemRow): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 32 26');
  svg.setAttribute('class', 'icon item-icon');
  if (!it.tested) svg.innerHTML = '<circle class="ring" cx="16" cy="13" r="7.5"/>';
  else {
    const opacity = it.recall === null ? 1 : Math.max(0.45, it.recall);
    svg.innerHTML = `<g class="badge c${Math.max(it.mastery, 1)}" opacity="${opacity.toFixed(2)}"><circle cx="16" cy="13" r="8.5"/><path d="M12.2 13.3l2.7 2.7 5-5.4"/></g>`;
  }
  return svg;
}

function itemRow(it: ItemRow): HTMLElement {
  const li = el('li', 'folder item', el('span', 'num'), itemIcon(it), el('span', 'name', it.name),
    el('span', 'count muted', it.due ? 'due' : ''));
  li.title = it.tested ? `${LEVELS[it.mastery]}, recall now ${Math.round((it.recall ?? 1) * 100)} %` : LEVELS[it.mastery];
  li.tabIndex = 0;
  let detail: HTMLElement | null = null;
  li.onclick = async () => {
    if (detail) return void (detail.remove(), detail = null);
    const d = await api('GET', `/api/item?ref=${encodeURIComponent(it.ref)}`);
    detail = el('li', 'item-detail',
      md(`**${d.label}** — ${d.gloss}`), ...(d.body ? [md(d.body)] : []), ...(d.mnemonic ? [md(`💡 ${d.mnemonic}`)] : []),
      ...(d.anecdote ? [md(`📖 ${d.anecdote}`)] : []), ...d.notes.map((n: string) => md(`📝 ${n}`)),
      el('p', 'muted', `${d.ref} · ${d.cards} card${d.cards === 1 ? '' : 's'} · ${d.state.reps} answers, ${d.state.lapses} forgotten`
        + (d.state.last_seen ? ` · last seen ${d.state.last_seen}` : '')));
    if (me.admin) detail.append(button('Edit', async () => {
      const src = await api('GET', `/api/item/source?ref=${encodeURIComponent(it.ref)}`);
      if (src.locked) return void detail!.append(el('p', 'muted', src.locked));
      const subject = location.hash.slice(1).split('/').slice(1).join('/');
      itemForm(src.fields, async (fields) => {
        await api('PUT', '/api/item', { ref: it.ref, fields });
        await refresh(decodeURIComponent(subject));
      }, detail!);
    }, 'link'));
    li.after(detail);
  };
  li.onkeydown = (e) => { if (e.key === 'Enter') li.click(); };
  return li;
}

function row(label: string, path: string, s: Subject | undefined, folder: boolean): HTMLElement {
  const li = el('li', 'folder', el('span', 'num muted', s?.order != null ? String(s.order) : ''), icon(s, folder),
    el('span', 'name', label), ...(s ? [el('span', 'count muted', stats(s))] : []));
  li.tabIndex = 0;
  li.onclick = () => go(path ? `#browse/${path}` : '#browse');
  li.onkeydown = (e) => { if (e.key === 'Enter') li.click(); };
  return li;
}

// --- the chat -----------------------------------------------------------

let source: EventSource | null = null;
const exercises = new Map<string, HTMLElement>();

function openSession(): void {
  source?.close();
  exercises.clear();
  $('transcript').replaceChildren();
  view('chat');
  source = new EventSource('/api/session/events');
  source.onmessage = (m) => show(JSON.parse(m.data));
}

$('composer').onsubmit = async (e) => {
  e.preventDefault();
  const input = $<HTMLTextAreaElement>('input');
  if (!input.value.trim()) return;
  await api('POST', '/api/session/message', { text: input.value });
  input.value = '';
};
$('input').onkeydown = (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    $<HTMLFormElement>('composer').requestSubmit();
  }
};

function add(node: HTMLElement): void {
  $('transcript').append(node);
  node.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function bubble(from: string, text: string): HTMLElement {
  return el('div', `msg ${from}`, md(text));
}

const MARK: Record<string, string> = { good: '✓', easy: '✓', hard: '≈', fail: '✗' };

function show(e: Ev): void {
  const box = e.id ? exercises.get(e.id) : undefined;
  switch (e.type) {
    case 'start':
      $('composer').hidden = !e.goal.teacher;
      add(el('p', 'muted center', e.goal.teacher ? 'Session started, the teacher is joining…' : 'Practice started.'));
      break;
    case 'learner_message': add(bubble('learner', e.text)); break;
    case 'message': add(bubble(e.from === 'pauk' ? 'pauk' : 'teacher', e.text)); break;
    case 'item_card':
      add(el('div', 'item-card', md(`**${e.label}** — ${e.gloss}`),
        ...(e.body ? [md(e.body)] : []), ...(e.mnemonic ? [md(`💡 ${e.mnemonic}`)] : []), ...(e.anecdote ? [md(`📖 ${e.anecdote}`)] : []))); break;
    case 'exercise': add(exercise(e)); break;
    case 'answered': if (box) result(box, e); break;
    case 'graded': if (box) result(box, { ...e, outcome: worst(Object.values(e.outcomes)) }); break;
    case 'override': if (box) box.append(el('p', 'muted', `Corrected: ${e.reason}`)); break;
    case 'hint': if (box) box.append(el('div', 'hint', md(`Hint: ${e.text}`))); break;
    case 'explanation': if (box) box.append(el('div', 'explanation', md(e.text))); break;
    case 'item_added': add(el('p', 'muted center', `New item: ${e.label}`)); break;
    case 'status':
      $('status').textContent = e.teacher === 'thinking' ? 'teacher is thinking…' : e.teacher === 'idle' ? '' : e.text ?? '';
      if (e.teacher === 'error' || e.teacher === 'budget') add(el('p', 'bad center', e.text));
      break;
    case 'ended':
      add(el('div', 'summary', ...(e.summary ? [md(e.summary)] : []), button('Back to the start page', () => { history.replaceState(null, '', '#browse'); home(); })));
      $('composer').hidden = true;
      $('status').textContent = '';
      source?.close();
      break;
  }
}

function worst(outcomes: (string | null)[]): string {
  return ['fail', 'hard', 'good', 'easy'].find((o) => outcomes.includes(o)) ?? 'good';
}

// One exercise widget; `answer` posts the response and locks it.
function exercise(e: Ev): HTMLElement {
  const ex = e.exercise;
  const box = el('div', 'exercise', md(ex.prompt));
  exercises.set(e.id!, box);
  const answer = (resp: unknown) => {
    box.classList.add('answered');
    box.querySelectorAll('button, input, select, textarea').forEach((c) => ((c as HTMLInputElement).disabled = true));
    api('POST', '/api/session/answer', { id: e.id, resp }).catch((err) => box.append(el('p', 'bad', err.message)));
  };
  const form = el('div', 'answer');
  if (ex.kind === 'mc') {
    const chosen = new Set<string>();
    for (const opt of ex.options) {
      const b = button('', () => {
        if (chosen.has(opt)) chosen.delete(opt);
        else chosen.add(opt);
        b.classList.toggle('chosen');
      }, 'option');
      b.append(md(opt, true));
      form.append(b);
    }
    form.append(button('Check', () => answer({ selected: [...chosen] })));
  } else if (ex.kind === 'text') {
    const input = el('input') as HTMLInputElement;
    input.autocapitalize = 'off';
    // braces matter: an on-handler that returns false cancels the key, so nothing could be typed
    input.onkeydown = (k) => { if (k.key === 'Enter') answer({ text: input.value }); };
    form.append(input, button('Check', () => answer({ text: input.value })));
    setTimeout(() => input.focus());
  } else if (ex.kind === 'match') {
    const selects = ex.left.map((left: string) => {
      const s = el('select') as HTMLSelectElement;
      s.append(el('option', '', '…'), ...ex.right.map((r: string) => el('option', '', r)));
      form.append(el('label', 'pair', md(left, true), s));
      return s;
    });
    form.append(button('Check', () => answer({ right: selects.map((s: HTMLSelectElement) => s.value) })));
  } else if (ex.kind === 'open') {
    const text = el('textarea') as HTMLTextAreaElement;
    form.append(text, button('Send', () => answer({ text: text.value })));
  } else if (ex.kind === 'recall') {
    form.append(button('Reveal the answer', async () => {
      const { reference } = await api('POST', '/api/session/reveal', { id: e.id });
      form.replaceChildren(el('div', 'reference', md(reference)), el('p', 'muted', 'How well did you know it?'),
        ...['fail', 'hard', 'good', 'easy'].map((o) => button({ fail: 'Not at all', hard: 'Partly', good: 'Well', easy: 'Easily' }[o]!, () => answer({ self: o }), 'secondary')));
    }));
  }
  box.append(form);
  if (me?.llm && $('composer').hidden === false) box.append(button('Explain', () => api('POST', '/api/session/explain', { id: e.id }), 'link'));
  return box;
}

function result(box: HTMLElement, e: Ev): void {
  box.classList.add('answered', e.outcome ?? 'waiting');
  box.querySelectorAll('.answer button, .answer input, .answer select, .answer textarea').forEach((c) => ((c as HTMLInputElement).disabled = true));
  if (e.waiting_for) return void box.append(el('p', 'muted', 'Waiting for the teacher…'));
  const expected = Array.isArray(e.expected)
    ? e.expected.map((x: unknown) => (Array.isArray(x) ? `${x[0]} → ${x[1]}` : String(x))).join(', ') : '';
  box.append(el('div', `verdict ${e.outcome}`, md(`${MARK[e.outcome] ?? ''} ${e.feedback ?? (e.outcome === 'good' || e.outcome === 'easy' ? '' : expected)}`)));
}

home().catch(() => view('login'));
