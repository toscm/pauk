// Grading and the memory model, with the cases of the PHP API's unit
// tests: v2 must judge and remember exactly like v1.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { gradeText, normalize, norm, slug, typoDistance, refError } from '../src/text.ts';
import { capHinted, mastery, step } from '../src/memory.ts';
import { grade, publicView, type Exercise } from '../src/grader.ts';

test('normalize', () => {
  const cases: [string, string][] = [
    ['Mitochondrium', 'mitochondrium'], ['  la   casa \n', 'la casa'], ['perché è così', 'perche e cosi'],
    ['Buon giorno!', 'buon giorno'], ["l'amica", 'l amica'], ['Straße', 'strasse'], ['a + b = c', 'a b c'],
    ['   ', ''], ['αλφα', 'αλφα'],
  ];
  for (const [input, out] of cases) assert.equal(normalize(input), out, input);
});

test('gradeText', () => {
  const cases: [string, string[], string][] = [
    ['essere', ['essere'], 'exact'], ['  Essere! ', ['essere'], 'exact'], ['perche', ['perché'], 'exact'],
    ['auto', ['la macchina', 'auto'], 'exact'], ['esere', ['essere'], 'typo'], ['esre', ['essere'], 'wrong'],
    ['mitochondrum', ['Mitochondrium'], 'typo'], ['avere', ['essere'], 'wrong'], ['', ['essere'], 'wrong'],
    ['   ', ['essere'], 'wrong'], ['casa', ['la casa', 'casa'], 'exact'], ['b', ['a'], 'wrong'],
    ['unn', ['uno'], 'wrong'], ['caza', ['casa'], 'typo'], ['faro', ['fare'], 'wrong'], ['como', ['come'], 'wrong'],
    ['por favore', ['per favore'], 'wrong'], ['cesa', ['casa'], 'wrong'], ['καλο', ['καλά'], 'wrong'],
    ['farfala', ['farfalla'], 'typo'], ['prego', ['pregoo'], 'typo'],
    ['la ragazza bella', ['la ragazzo bella'], 'typo'], ['abcdefghijklmnxx', ['abcdefghijklmnop'], 'typo'],
    ['abcdefghijklmxxx', ['abcdefghijklmnop'], 'wrong'], ['esserx', ['essere'], 'typo'], ['essexx', ['essere'], 'wrong'],
  ];
  for (const [answer, accepted, out] of cases) assert.equal(gradeText(answer, accepted), out, `${answer} vs ${accepted}`);
  assert.equal(typoDistance('faro', 'fare'), 2);
  assert.equal(typoDistance('fare', 'fate'), 1);
});

test('keys', () => {
  assert.equal(slug('α'), 'alpha');
  assert.equal(slug('La farfalla'), 'la-farfalla');
  assert.equal(norm('**word** (noun)'), 'word');
  assert.equal(refError('it/essere.pres.1sg'), null);
  assert.match(refError('it/Essere')!, /lowercase/);
  assert.match(refError('essere')!, /space\/key/);
});

const DAY = 86_400_000;

test('memory model pauk-mm@1', () => {
  const intro = step(null, 'introduce', null, 0);
  assert.equal(intro.stability, 0.2);
  assert.equal(mastery(intro), 1);
  const good = step(null, 'recall', 'good', 0);
  assert.equal(good.stability, 3);
  assert.equal(good.best, 'recall');
  assert.ok(Math.abs(step(null, 'recognize', 'good', 0).stability - 1.8) < 1e-9, 'recognition is weaker evidence');
  assert.deepEqual(step(good, 'introduce', null, 5 * DAY), good, 'introducing never changes a state');
  assert.ok(step(good, 'recall', 'good', 60_000).stability < 3.1, 'cramming barely helps');
  assert.ok(Math.abs(step(good, 'recall', 'good', 3 * DAY).stability / 3 - 2.13) < 0.05);
  const failed = step(step(good, 'recall', 'good', 27 * DAY), 'recall', 'fail', 50 * DAY);
  assert.equal(failed.lapses, 1);
  assert.equal(mastery(null), 0);
  assert.equal(mastery({ ...good, stability: 100, best: 'recognize' }), 4, 'level 5 needs recall');
  assert.equal(mastery({ ...good, stability: 100, best: 'recall' }), 5);
  assert.equal(capHinted('easy', true), 'hard');
  assert.equal(capHinted('fail', true), 'fail');
});

test('grade keyed exercises, and the browser never sees the key', () => {
  const mc: Exercise = { kind: 'mc', items: ['it/lo'], prompt: '?', options: ['lo', 'il'], correct: ['lo'] };
  assert.equal(grade(mc, { selected: ['lo'] }).outcome, 'good');
  assert.equal(grade(mc, { selected: ['lo', 'il'] }).outcome, 'fail');
  assert.equal('correct' in publicView(mc), false);
  const match: Exercise = { kind: 'match', items: ['it/essere'], prompt: '?', pairs: [['io', 'sono'], ['tu', 'sei']] };
  assert.equal(grade(match, { right: ['sono', 'sei'] }).outcome, 'good');
  assert.equal(grade(match, { right: ['sei', 'sono'] }).outcome, 'fail');
  assert.equal(JSON.stringify(publicView(match)).includes('"pairs"'), false);
  const text: Exercise = { kind: 'text', items: ['it/essere'], prompt: '?', accepted: ['essere'] };
  assert.equal(grade(text, { text: 'esere' }).outcome, 'hard');
});
