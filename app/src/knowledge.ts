// Knowledge files: YAML decks and Markdown items in source folders,
// read into an in-memory index. pauk writes them only when someone edits or
// adds an item in the app (src/edit.ts) and when a user's own items.yaml
// grows. docs/files.md is the format contract.

import fs from 'node:fs';
import path from 'node:path';
import YAML, { LineCounter, isMap, isSeq, type Node } from 'yaml';
import { KINDS, refError } from './text.ts';

export interface Card {
  id: string;                // position in the files, valid for one load only
  type: 'text' | 'mc' | 'match' | 'recall';
  q: string;
  answer: string[];          // accepted answers (text, mc) or the reference (recall)
  wrong: string[];           // mc distractors
  pairs: [string, string][]; // match
  items: string[];           // refs this card is evidence for
}

export interface Item {
  ref: string;
  space: string;
  key: string;
  kind: string;
  label: string;
  gloss: string;
  body: string;
  priority: number;          // 0..100, default 50
  level: number | null;
  mnemonic: string;
  anecdote: string;
  subjects: string[];        // the file's subject plus `also`
  aliases: string[];         // old refs that resolve to this item
  links: { rel: string; to: string }[];
  cards: Card[];
  where: string;             // file:line
  file: string;              // the file that defines it
}

export interface Issue { where: string; message: string }

export interface Knowledge {
  items: Map<string, Item>;
  aliases: Map<string, string>;
  cards: Map<string, Card>;
  subjects: Set<string>;
  order: Map<string, number>;   // subject -> its number from a "01-" name prefix
  errors: Issue[];
  warnings: Issue[];
  media: string[];           // source roots, indexed by /files/<n>/...
}

export const FORMAT = 1;
const RELS = ['requires', 'part_of', 'related'];
const CARD_TYPES = ['text', 'mc', 'match', 'recall'];

export function emptyKnowledge(): Knowledge {
  return { items: new Map(), aliases: new Map(), cards: new Map(), subjects: new Set(), order: new Map(), errors: [], warnings: [], media: [] };
}

// Load every source folder (in order) into one index, then resolve links.
export function loadKnowledge(roots: string[], k = emptyKnowledge()): Knowledge {
  for (const root of roots) {
    if (!fs.existsSync(root)) {
      k.errors.push({ where: root, message: 'source folder does not exist' });
      continue;
    }
    const n = k.media.push(root) - 1;
    const manifest = path.join(root, 'pauk.yaml');
    if (fs.existsSync(manifest)) {
      const format = YAML.parse(fs.readFileSync(manifest, 'utf8'))?.format;
      if (format !== FORMAT) k.errors.push({ where: manifest, message: `format ${format}, this pauk reads format ${FORMAT}` });
    }
    for (const file of walk(root)) loadFile(k, root, file, n);
  }
  return link(k);
}

function* walk(dir: string): Generator<string> {
  for (const e of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    if (e.name.startsWith('.') || e.name === 'media' || e.name === 'node_modules') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) yield* walk(p);
    else if ((/\.ya?ml$/.test(e.name) && e.name !== 'pauk.yaml') || e.name.endsWith('.md') && e.name !== 'README.md') yield p;
  }
}

// Load one file. `subject` defaults to its path below the source root.
export function loadFile(k: Knowledge, root: string, file: string, n: number, subject?: string): void {
  const rel = path.relative(root, file);
  subject ??= subjectOf(k, rel);
  const text = fs.readFileSync(file, 'utf8');
  const lines = new LineCounter();
  let doc: Node | null;
  let body = '';
  if (file.endsWith('.md')) {
    // one item: YAML frontmatter, the Markdown below it is the body
    const m = /^---\n([\s\S]*?)\n---\n?([\s\S]*)$/.exec(text);
    if (!m) return void k.errors.push({ where: rel, message: 'a Markdown item needs YAML frontmatter between --- lines' });
    doc = YAML.parseDocument(m[1], { lineCounter: lines }).contents;
    body = m[2].trim();
  } else {
    const d = YAML.parseDocument(text, { lineCounter: lines });
    for (const e of d.errors) k.errors.push({ where: `${rel}:${e.linePos?.[0].line ?? '?'}`, message: e.message });
    if (d.errors.length) return;
    doc = d.contents;
  }
  const at = (node: Node | null | undefined) => `${rel}:${node?.range ? lines.linePos(node.range[0]).line : 1}`;
  const data = doc ? (doc.toJSON() as Record<string, unknown>) : {};
  const fileAlso = strings(data.also);
  const media = (s: string) => s.replace(/(\]\()(media\/)/g, `$1/files/${n}/$2`);

  if (file.endsWith('.md')) {
    addItem(k, { ...data, body: data.body ?? body }, String(data.space ?? ''), [subject.replace(/\/[^/]+$/, ''), ...fileAlso], at(doc), media, file);
    return;
  }
  const space = String(data.space ?? '');
  const seq = (name: string): Node[] => {
    const node = isMap(doc) ? doc.get(name, true) : null;
    return isSeq(node) ? (node.items as Node[]) : [];
  };
  (Array.isArray(data.items) ? data.items : []).forEach((raw, i) => {
    addItem(k, raw as Record<string, unknown>, space, [subject, ...fileAlso], at(seq('items')[i]), media, file);
  });
  (Array.isArray(data.cards) ? data.cards : []).forEach((raw, i) => {
    const where = at(seq('cards')[i]);
    const card = parseCard(k, raw as Record<string, unknown>, space, null, `${rel}#c${i}`, where, media);
    if (card && card.items.length === 0) k.errors.push({ where, message: 'a card outside an item needs `items`' });
  });
  if (data.items === undefined && data.cards === undefined) k.warnings.push({ where: rel, message: 'no items and no cards' });
}

// italian/01-a1/04-numbers.yaml is subject italian/a1/numbers; the numbers
// give the order in which the subjects are meant to be learned.
function subjectOf(k: Knowledge, rel: string): string {
  const parts: string[] = [];
  for (const seg of rel.replace(/\.(ya?ml|md)$/, '').split(path.sep)) {
    const m = /^(\d+)-(.+)$/.exec(seg);
    parts.push(m ? m[2] : seg);
    if (m && !k.order.has(parts.join('/'))) k.order.set(parts.join('/'), Number(m[1]));
  }
  return parts.join('/');
}

function addItem(k: Knowledge, d: Record<string, unknown>, fileSpace: string, subjects: string[], where: string,
  media: (s: string) => string, file: string): void {
  const space = String(d.space ?? fileSpace);
  const key = String(d.key ?? '');
  const ref = `${space}/${key}`;
  const err = refError(ref);
  if (err) return void k.errors.push({ where, message: err });
  if (d.extend === true) return extendItem(k, ref, d, subjects, where, media);
  if (k.items.has(ref)) return void k.errors.push({ where, message: `${ref} is already defined in ${k.items.get(ref)!.where}` });
  const kind = String(d.kind ?? 'other');
  if (!KINDS.includes(kind)) k.errors.push({ where, message: `kind "${kind}" is not one of ${KINDS.join(', ')}` });
  const qualify = (r: string) => (r.includes('/') ? r : `${space}/${r}`);
  const item: Item = {
    ref, space, key, kind,
    label: media(String(d.label ?? key)),
    gloss: media(String(d.gloss ?? '')),
    body: media(String(d.body ?? '')),
    priority: Number(d.priority ?? 50),
    level: d.level == null ? null : Number(d.level),
    mnemonic: String(d.mnemonic ?? ''),
    anecdote: String(d.anecdote ?? ''),
    subjects: [...new Set([...subjects, ...strings(d.also)].filter(Boolean))],
    aliases: strings(d.aliases).map(qualify),
    links: RELS.flatMap((rel) => strings(d[rel]).map((to) => ({ rel, to: qualify(to) }))),
    cards: [],
    where,
    file,
  };
  k.items.set(ref, item);
  item.subjects.forEach((s) => k.subjects.add(s));
  (Array.isArray(d.cards) ? d.cards : []).forEach((raw, i) =>
    parseCard(k, raw as Record<string, unknown>, space, ref, `${ref}#${i}`, `${where} (card ${i + 1})`, media));
}

// `extend: true`: a later source (e.g. a private one) adds to an item of an
// earlier source: more body, cards, links and aliases (and subjects only
// through `also`; the extending file's own place does not move the item).
function extendItem(k: Knowledge, ref: string, d: Record<string, unknown>, _subjects: string[], where: string,
  media: (s: string) => string): void {
  const item = k.items.get(ref);
  if (!item) return void k.errors.push({ where, message: `extend: ${ref} is not defined in an earlier file or source` });
  const qualify = (r: string) => (r.includes('/') ? r : `${item.space}/${r}`);
  if (d.body) item.body = [item.body, media(String(d.body))].filter(Boolean).join('\n\n');
  for (const f of ['mnemonic', 'anecdote'] as const) if (d[f] && !item[f]) item[f] = String(d[f]);
  item.subjects = [...new Set([...item.subjects, ...strings(d.also)].filter(Boolean))];   // only `also` places it elsewhere
  item.subjects.forEach((s) => k.subjects.add(s));
  item.aliases.push(...strings(d.aliases).map(qualify));
  item.links.push(...RELS.flatMap((rel) => strings(d[rel]).map((to) => ({ rel, to: qualify(to) }))));
  (Array.isArray(d.cards) ? d.cards : []).forEach((raw, i) =>
    parseCard(k, raw as Record<string, unknown>, item.space, ref, `${ref}#x${where}#${i}`, `${where} (card ${i + 1})`, media));
}

function parseCard(k: Knowledge, d: Record<string, unknown>, space: string, owner: string | null, id: string, where: string,
  media: (s: string) => string): Card | null {
  const type = String(d.type ?? '') as Card['type'];
  if (!CARD_TYPES.includes(type)) return void k.errors.push({ where, message: `card type must be one of ${CARD_TYPES.join(', ')}` }), null;
  const q = media(String(d.q ?? ''));
  if (!q) return void k.errors.push({ where, message: 'card needs q (the question)' }), null;
  const card: Card = {
    id, type, q,
    answer: strings(d.answer).map(media),
    wrong: strings(d.wrong).map(media),
    pairs: Array.isArray(d.pairs) ? (d.pairs as unknown[]).map((p) => (Array.isArray(p) ? [String(p[0]), String(p[1])] : ['', ''])) : [],
    items: [...new Set([...(owner ? [owner] : []), ...strings(d.items).map((r) => (r.includes('/') ? r : `${space}/${r}`))])],
  };
  const problem = type === 'match' ? (card.pairs.length < 2 ? 'a match card needs at least two pairs' : null)
    : card.answer.length === 0 ? `a ${type} card needs answer`
    : type === 'mc' && card.wrong.length === 0 ? 'an mc card needs wrong options' : null;
  if (problem) return void k.errors.push({ where, message: problem }), null;
  k.cards.set(id, card);
  return card;
}

// Resolve aliases, attach top-level cards to their items, check links.
function link(k: Knowledge): Knowledge {
  for (const item of k.items.values()) {
    for (const a of item.aliases) {
      if (k.items.has(a)) k.errors.push({ where: item.where, message: `alias ${a} is also an item` });
      else if (k.aliases.has(a)) k.errors.push({ where: item.where, message: `alias ${a} is already an alias of ${k.aliases.get(a)}` });
      else k.aliases.set(a, item.ref);
    }
  }
  for (const card of k.cards.values()) {
    card.items = card.items.map((r) => resolve(k, r) ?? r);
    for (const r of card.items) {
      const item = k.items.get(r);
      if (!item) k.errors.push({ where: card.id, message: `card refers to unknown item ${r}` });
      else if (!item.cards.includes(card)) item.cards.push(card);
    }
  }
  for (const item of k.items.values()) {
    for (const l of item.links) {
      const to = resolve(k, l.to);
      if (to) l.to = to;
      else k.warnings.push({ where: item.where, message: `${l.rel} ${l.to}: no such item` });
    }
  }
  shape(k);
  return k;
}

// The browser shows every subject as a folder that holds either subfolders
// or items, never both, and at most MAX_ITEMS items (aim for 5 to 10).
export const MAX_ITEMS = 12;
function shape(k: Knowledge): void {
  const direct = new Map<string, Item[]>();
  for (const item of k.items.values()) for (const s of item.subjects) direct.set(s, [...(direct.get(s) ?? []), item]);
  const parents = new Set([...k.subjects].flatMap((s) => s.split('/').slice(0, -1).map((_, i, p) => p.slice(0, i + 1).join('/'))));
  for (const [s, items] of direct) {
    if (parents.has(s)) k.warnings.push({ where: s, message: `holds ${items.length} items and subfolders: move the items into a subfolder (${items.slice(0, 3).map((i) => i.where).join(', ')})` });
    else if (items.length > MAX_ITEMS) k.warnings.push({ where: s, message: `holds ${items.length} items, more than ${MAX_ITEMS}: split it` });
  }
}

export function resolve(k: Knowledge, ref: string): string | null {
  return k.items.has(ref) ? ref : k.aliases.get(ref) ?? null;
}

// Items of a subject, including the subjects below it.
export function inSubject(item: Item, subject: string | undefined): boolean {
  return !subject || item.subjects.some((s) => s === subject || s.startsWith(subject + '/'));
}

function strings(v: unknown): string[] {
  if (v == null) return [];
  return (Array.isArray(v) ? v : [v]).map(String);
}

// Append an item to a user's own items.yaml (the only file pauk writes).
export function appendItem(file: string, item: Record<string, unknown>): void {
  if (!fs.existsSync(file)) fs.writeFileSync(file, '# Items your teacher added. Edit, move or delete them freely.\nitems:\n');
  const block = YAML.stringify([item], { lineWidth: 0 }).replace(/^/gm, '  ').trimEnd();
  fs.appendFileSync(file, block + '\n');
}
