// Exercises and their grading. An exercise is plain JSON, written by the
// teacher or built from a card; keyed kinds are graded here, instantly.

import type { Card } from './knowledge.ts';
import type { Mode, Outcome } from './memory.ts';
import { gradeText, type Match } from './text.ts';

export interface Exercise {
  kind: 'mc' | 'text' | 'match' | 'open' | 'recall';
  items: string[];
  prompt: string;
  mode?: Mode;
  options?: string[];       // mc, in display order
  correct?: string[];       // mc: the correct options
  accepted?: string[];      // text
  pairs?: [string, string][]; // match, in correct order
  reference?: string;       // open, recall
}

export const KEYED = ['mc', 'text', 'match'];
const DEFAULT_MODE: Record<Exercise['kind'], Mode> = { mc: 'recognize', match: 'recognize', text: 'recall', recall: 'recall', open: 'produce' };

export function modeOf(ex: Exercise): Mode {
  return ex.mode ?? DEFAULT_MODE[ex.kind];
}

// Null if the exercise is well-formed, else what is wrong.
export function exerciseError(ex: Exercise): string | null {
  if (!ex || !DEFAULT_MODE[ex.kind]) return 'kind must be mc, text, match, open or recall';
  if (!Array.isArray(ex.items) || ex.items.length === 0) return 'items must list the refs this exercise tests';
  if (!ex.prompt) return 'prompt is required';
  if (ex.kind === 'mc' && !(ex.options?.length && ex.correct?.length && ex.correct.every((c) => ex.options!.includes(c))))
    return 'mc needs options and correct (a subset of options)';
  if (ex.kind === 'text' && !ex.accepted?.length) return 'text needs accepted answers';
  if (ex.kind === 'match' && !((ex.pairs?.length ?? 0) >= 2)) return 'match needs at least two pairs';
  if ((ex.kind === 'open' || ex.kind === 'recall') && !ex.reference) return `${ex.kind} needs reference`;
  return null;
}

// What the learner's browser may see: the key is removed, options shuffled.
export function publicView(ex: Exercise) {
  const { correct: _c, accepted: _a, reference: _r, ...rest } = ex;
  if (ex.kind === 'match') return { ...rest, pairs: undefined, left: ex.pairs!.map((p) => p[0]), right: shuffle(ex.pairs!.map((p) => p[1])) };
  return rest;
}

export interface Graded { grader: string; match: Match; outcome: Outcome; expected: unknown }

// Response shapes: mc {selected: string[]}, text {text}, match {right: string[]} (one per left).
export function grade(ex: Exercise, resp: Record<string, unknown>): Graded {
  let grader: string;
  let match: Match;
  if (ex.kind === 'mc') {
    const sel = new Set((resp.selected as string[]) ?? []);
    grader = 'mc@1';
    match = sel.size === ex.correct!.length && ex.correct!.every((c) => sel.has(c)) ? 'exact' : 'wrong';
  } else if (ex.kind === 'text') {
    grader = 'text@2';
    match = gradeText(String(resp.text ?? ''), ex.accepted!);
  } else if (ex.kind === 'match') {
    const right = (resp.right as string[]) ?? [];
    grader = 'match@1';
    match = ex.pairs!.every((p, i) => right[i] === p[1]) ? 'exact' : 'wrong';
  } else {
    throw new Error(`${ex.kind} is not keyed`);
  }
  const outcome = ({ exact: 'good', typo: 'hard', wrong: 'fail' } as const)[match];
  const expected = ex.kind === 'mc' ? ex.correct : ex.kind === 'text' ? ex.accepted : ex.pairs;
  return { grader, match, outcome, expected };
}

// The exercise a card asks.
export function fromCard(card: Card): Exercise {
  const base = { items: card.items, prompt: card.q };
  if (card.type === 'mc') return { ...base, kind: 'mc', options: shuffle([...card.answer, ...card.wrong]), correct: card.answer };
  if (card.type === 'text') return { ...base, kind: 'text', accepted: card.answer };
  if (card.type === 'match') return { ...base, kind: 'match', pairs: card.pairs };
  return { ...base, kind: 'recall', reference: card.answer.join('\n\n') };
}

export function shuffle<T>(a: T[]): T[] {
  const b = [...a];
  for (let i = b.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [b[i], b[j]] = [b[j], b[i]];
  }
  return b;
}
