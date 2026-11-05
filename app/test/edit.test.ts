// Editing knowledge from the app (src/edit.ts) in a scratch source.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadKnowledge } from '../src/knowledge.ts';
import { addFolder, addItem, itemSource, notEditable, updateItem } from '../src/edit.ts';

function scratch() {
  const builtin = fs.mkdtempSync(path.join(os.tmpdir(), 'pauk-builtin-'));
  const src = fs.mkdtempSync(path.join(os.tmpdir(), 'pauk-src-'));
  fs.mkdirSync(path.join(src, 'greek'));
  fs.writeFileSync(path.join(src, 'greek', '01-letters.yaml'),
    'space: el\nitems:\n  - key: alpha\n    kind: symbol\n    label: α\n    gloss: alpha\n    cards:\n      - type: text\n        q: "Name **α**"\n        answer: [alpha]\n');
  fs.writeFileSync(path.join(src, 'note.md'), '---\nspace: concepts\nkey: note\nlabel: A note\n---\nBody.\n');
  const sources = [builtin, src];
  return { src, sources, k: () => loadKnowledge(sources) };
}

test('an edit changes only the item in its deck, keeping the rest of the file', () => {
  const { src, sources, k } = scratch();
  const alpha = k().items.get('el/alpha')!;
  assert.equal(notEditable(sources, alpha), null);
  assert.deepEqual(itemSource(alpha), { kind: 'symbol', label: 'α', gloss: 'alpha' });
  updateItem(sources, alpha, { gloss: 'alpha, the first letter', body: 'line one\nline two', mnemonic: '' });
  const text = fs.readFileSync(path.join(src, 'greek', '01-letters.yaml'), 'utf8');
  assert.match(text, /gloss: alpha, the first letter\n    body: \|-\n      line one\n      line two\n    cards:/);
  assert.match(text, /answer: \[alpha\]/);
  assert.equal(k().items.get('el/alpha')!.body, 'line one\nline two');
  assert.match(notEditable(sources, k().items.get('concepts/note')!)!, /Markdown/);
});

test('new items get a key from their label; a full folder and an empty label are refused', () => {
  const { sources, k } = scratch();
  const ref = addItem(sources, k(), 'greek/letters', { label: 'β', gloss: 'beta' });
  assert.equal(ref, 'el/item');
  assert.equal(addItem(sources, k(), 'greek/letters', { label: 'Gamma *γ*', gloss: 'gamma' }), 'el/gamma');
  assert.throws(() => addItem(sources, k(), 'greek/letters', { label: '', gloss: 'x' }), /needs a label/);
  for (let i = 0; i < 9; i++) addItem(sources, k(), 'greek/letters', { label: `letter ${i}` });
  assert.throws(() => addItem(sources, k(), 'greek/letters', { label: 'one too many' }), /at most 12/);
  assert.equal(k().errors.length + k().warnings.length, 0);
});

test('a new folder is a numbered deck next to its siblings, with its first item', () => {
  const { src, sources, k } = scratch();
  const out = addFolder(sources, k(), 'greek', 'Archaic letters', { label: 'Koppa', gloss: 'Ϙ' });
  assert.deepEqual(out, { subject: 'greek/archaic-letters', ref: 'el/koppa' });
  assert.ok(fs.existsSync(path.join(src, 'greek', '02-archaic-letters.yaml')));
  assert.equal(k().order.get('greek/archaic-letters'), 2);
  assert.throws(() => addFolder(sources, k(), 'greek/letters', 'Sub', { label: 'x' }), /holds items/);
  assert.throws(() => addFolder(sources, k(), 'greek', 'Archaic letters', { label: 'x' }), /exists already/);
});
