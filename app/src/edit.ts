// Editing knowledge from the app: change an item in its deck, add an item to
// a folder, or start a new folder with its first item. Every write is checked
// like `pauk check`; a write that adds an error or a warning is undone.
// Only YAML decks in the configured sources are written, never the decks that
// ship with pauk (the first source) and never Markdown items.

import fs from 'node:fs';
import path from 'node:path';
import YAML, { isMap, isSeq, Scalar, type Document, type YAMLMap } from 'yaml';
import { loadKnowledge, type Item, type Knowledge } from './knowledge.ts';
import { KINDS, refError } from './text.ts';

export const FIELDS = ['kind', 'label', 'gloss', 'body', 'mnemonic', 'anecdote', 'priority', 'level'] as const;
export type Fields = Partial<Record<(typeof FIELDS)[number], string | number | null>>;

const MAX_ITEMS = 12;
// as the decks are written by hand: no line wrapping, [a, b] without padding
const FORMAT = { lineWidth: 0, flowCollectionPadding: false };

// Null if the app may write this item, else why not.
export function notEditable(sources: string[], item: Item): string | null {
  if (item.file.endsWith('.md')) return 'This item is a Markdown file: edit it in an editor.';
  const root = rootOf(sources, item.file);
  if (root === null) return 'This item is not in a knowledge source.';
  if (root === sources[0]) return 'This item ships with pauk.';
  return null;
}

// The item's fields as written in its file (without media rewriting).
export function itemSource(item: Item): Fields {
  const { node } = locate(item);
  const raw = node.toJSON() as Record<string, unknown>;
  return Object.fromEntries(FIELDS.filter((f) => raw[f] != null).map((f) => [f, raw[f] as string | number]));
}

export function updateItem(sources: string[], item: Item, fields: Fields): void {
  const reason = notEditable(sources, item);
  if (reason) throw new Error(reason);
  const { doc, node } = locate(item);
  apply(doc, node, clean(fields));
  write(sources, item.file, doc.toString(FORMAT));
}

// A new item in a folder that holds items; returns its ref.
export function addItem(sources: string[], k: Knowledge, subject: string, fields: Fields): string {
  const here = [...k.items.values()].filter((i) => i.subjects.includes(subject));
  if (here.length >= MAX_ITEMS) throw new Error(`This folder already holds ${here.length} items (at most ${MAX_ITEMS}): start a new folder instead.`);
  const file = mostCommon(here.filter((i) => i.subjects[0] === subject && !notEditable(sources, i)).map((i) => i.file));
  if (!file) throw new Error('No deck file of this folder can be written here: add the item in an editor.');
  const doc = YAML.parseDocument(fs.readFileSync(file, 'utf8'));
  const space = String(doc.get('space') ?? 'concepts');
  const node = doc.createNode({ key: uniqueKey(k, space, String(fields.label ?? '')) }) as YAMLMap;
  apply(doc, node, clean(fields));
  const items = doc.get('items');
  if (!isSeq(items)) throw new Error(`${file} has no items list`);
  items.items.push(node);
  write(sources, file, doc.toString(FORMAT));
  return `${space}/${node.get('key')}`;
}

// A new folder (a new deck file) below `parent` with its first item.
export function addFolder(sources: string[], k: Knowledge, parent: string, name: string, fields: Fields): { subject: string; ref: string } {
  const slug = slugify(name);
  if (!slug) throw new Error('The folder needs a name.');
  const subject = parent ? `${parent}/${slug}` : slug;
  if (k.subjects.has(subject)) throw new Error(`${subject} exists already.`);
  if ([...k.items.values()].some((i) => i.subjects.includes(parent) && parent)) throw new Error('This folder holds items, so it cannot hold folders as well.');
  const dir = folderDir(sources, k, parent);
  const siblings = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => !f.startsWith('.') && f !== 'media' && f !== 'pauk.yaml' && f !== 'README.md') : [];
  const numbers = siblings.map((f) => /^(\d+)-/.exec(f)?.[1]).filter(Boolean).map(Number);
  const file = path.join(dir, `${numbers.length ? `${String(Math.max(...numbers) + 1).padStart(2, '0')}-` : ''}${slug}.yaml`);
  const below = [...k.items.values()].filter((i) => i.subjects.some((s) => !parent || s.startsWith(parent + '/')));
  const space = mostCommon(below.map((i) => i.space)) ?? 'concepts';
  const doc = new YAML.Document({ space, items: [] });
  const node = doc.createNode({ key: uniqueKey(k, space, String(fields.label ?? '')) }) as YAMLMap;
  apply(doc, node, clean(fields));
  (doc.get('items') as YAML.YAMLSeq).items.push(node);
  fs.mkdirSync(dir, { recursive: true });
  write(sources, file, doc.toString(FORMAT));
  return { subject, ref: `${space}/${node.get('key')}` };
}

// --- helpers ---------------------------------------------------------------

function rootOf(sources: string[], file: string): string | null {
  return sources.find((r) => file.startsWith(path.resolve(r) + path.sep)) ?? null;
}

function locate(item: Item): { doc: Document; node: YAMLMap } {
  const doc = YAML.parseDocument(fs.readFileSync(item.file, 'utf8'));
  const space = String(doc.get('space') ?? '');
  const items = doc.get('items');
  const node = isSeq(items) ? items.items.find((n) => isMap(n) && String(n.get('key')) === item.key && String(n.get('space') ?? space) === item.space) : undefined;
  if (!isMap(node)) throw new Error(`${item.ref} is no longer in ${item.file}`);
  return { doc, node };
}

function clean(f: Fields): Fields {
  const out: Fields = {};
  for (const k of FIELDS) {
    if (f[k] === undefined) continue;
    const v = typeof f[k] === 'string' ? (f[k] as string).replace(/\r\n/g, '\n').trim() : f[k];
    out[k] = v === '' ? null : v;
  }
  if (out.label === null || (out.label === undefined && f.label !== undefined)) throw new Error('The item needs a label (the question or the word).');
  if (out.kind != null && !KINDS.includes(String(out.kind))) throw new Error(`kind must be one of ${KINDS.join(', ')}`);
  for (const n of ['priority', 'level'] as const) {
    if (out[n] == null) continue;
    const x = Number(out[n]);
    if (!Number.isInteger(x) || x < 0 || (n === 'priority' && x > 100)) throw new Error(`${n} must be a whole number${n === 'priority' ? ' from 0 to 100' : ''}`);
    out[n] = x;
  }
  return out;
}

// Set or remove the fields in a deck's item node; multi-line text as a block.
function apply(doc: Document, node: YAMLMap, f: Fields): void {
  for (const k of FIELDS) {
    if (f[k] === undefined) continue;
    if (f[k] === null) node.delete(k);
    else {
      const v = doc.createNode(f[k]) as Scalar;
      if (typeof f[k] === 'string' && (f[k] as string).includes('\n')) v.type = Scalar.BLOCK_LITERAL;
      if (node.has(k)) node.set(k, v);
      else {
        // a new field goes before the cards, links and other lists
        const at = node.items.findIndex((p) => !['space', 'key', ...FIELDS].includes(String((p.key as Scalar)?.value ?? p.key)));
        node.items.splice(at < 0 ? node.items.length : at, 0, doc.createPair(k, v));
      }
    }
  }
}

// Write a deck and check all sources; undo the write if it made things worse.
function write(sources: string[], file: string, text: string): void {
  const before = loadKnowledge(sources);
  const old = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null;
  fs.writeFileSync(file, text.endsWith('\n') ? text : text + '\n');
  const after = loadKnowledge(sources);
  const seen = new Set([...before.errors, ...before.warnings].map((p) => p.message));
  const fresh = [...after.errors, ...after.warnings].filter((p) => !seen.has(p.message));
  if (after.errors.length > before.errors.length || after.warnings.length > before.warnings.length) {
    if (old === null) fs.rmSync(file);
    else fs.writeFileSync(file, old);
    throw new Error(`Not saved: ${fresh[0] ? `${fresh[0].where}: ${fresh[0].message}` : 'it would add a problem (pauk check)'}`);
  }
}

// The directory of a folder that holds folders ('' is the first writable source).
function folderDir(sources: string[], k: Knowledge, parent: string): string {
  if (!parent) {
    if (!sources[1]) throw new Error('No knowledge source to write to: add one to config.yaml.');
    return sources[1];
  }
  const depth = parent.split('/').length;
  for (const i of k.items.values()) {
    const root = rootOf(sources, i.file);
    if (!root || root === sources[0] || !i.subjects[0]?.startsWith(parent + '/')) continue;
    return path.join(root, ...path.relative(root, i.file).split(path.sep).slice(0, depth));
  }
  throw new Error(`No folder for ${parent} in a writable source.`);
}

function slugify(s: string): string {
  return s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/, '');
}

function uniqueKey(k: Knowledge, space: string, label: string): string {
  const base = slugify(label.replace(/[*_`[\]()]/g, '')) || 'item';
  let key = base;
  for (let n = 2; k.items.has(`${space}/${key}`) || k.aliases.has(`${space}/${key}`); n++) key = `${base}-${n}`;
  const err = refError(`${space}/${key}`);
  if (err) throw new Error(err);
  return key;
}

function mostCommon<T>(xs: T[]): T | undefined {
  const n = new Map<T, number>();
  for (const x of xs) n.set(x, (n.get(x) ?? 0) + 1);
  return [...n].sort((a, b) => b[1] - a[1])[0]?.[0];
}
