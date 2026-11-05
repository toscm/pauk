// The memory model pauk-mm@1, ported unchanged from the PHP API: a pure
// function from (state, event) to state. Item states are never stored;
// they are this function folded over the learning log in time order.

export const MODEL = 'pauk-mm@1';

export type Mode = 'introduce' | 'recognize' | 'recall' | 'produce' | 'explain' | 'self_report';
export type Outcome = 'fail' | 'hard' | 'good' | 'easy';
export const MODES: Mode[] = ['introduce', 'recognize', 'recall', 'produce', 'explain', 'self_report'];
export const OUTCOMES: Outcome[] = ['fail', 'hard', 'good', 'easy'];

export interface State {
  stability: number;   // days until recall drops to 90 %
  difficulty: number;  // 1..10
  first: number;       // first seen, ms since epoch
  last: number;        // last seen
  reps: number;
  lapses: number;
  best: Mode | null;   // strongest mode answered correctly
}

const MODE_FACTOR = { recognize: 0.6, recall: 1.0, produce: 1.2, explain: 1.0, self_report: 0.5 };
const FIRST_S = { hard: 1, good: 3, easy: 8 };
const FIRST_D = { fail: 7, hard: 6, good: 5, easy: 3 };
const GROWTH_K = { hard: 4, good: 10, easy: 16 };
const D_DELTA = { fail: 1, hard: 0.5, good: 0, easy: -0.5 };
const MIN_S = 0.2;
const CURVE = 9;   // R = 1 / (1 + t / (9 S)), so R(S) = 0.9
const RANK: Partial<Record<Mode, number>> = { recognize: 1, recall: 2, explain: 2, produce: 3 };
const DAY = 86_400_000;

export function step(state: State | null, mode: Mode, outcome: Outcome | null, at: number): State {
  if (mode === 'introduce') {
    // presenting tests nothing: it creates a state but never changes one
    return state ?? { stability: MIN_S, difficulty: 5, first: at, last: at, reps: 0, lapses: 0, best: null };
  }
  if (outcome === null) throw new Error(`mode ${mode} needs an outcome`);
  const m = MODE_FACTOR[mode];
  const ok = outcome !== 'fail';
  let s: State;
  if (state === null) {
    s = {
      stability: ok ? m * FIRST_S[outcome as 'hard'] : MIN_S, difficulty: FIRST_D[outcome],
      first: at, last: at, reps: 1, lapses: ok ? 0 : 1, best: null,
    };
  } else {
    s = { ...state };
    const r = recall(s.stability, Math.max(0, at - s.last) / DAY);
    if (ok) {
      const growth = 1 + m * GROWTH_K[outcome as 'hard'] * ((11 - s.difficulty) / 10)
        * s.stability ** -0.15 * (Math.exp(2 * (1 - r)) - 1);
      s.stability *= growth;
    } else {
      s.stability = Math.max(MIN_S, Math.min(s.stability / 2, 0.5 + 0.1 * s.stability));
      s.lapses++;
    }
    s.difficulty = Math.max(1, Math.min(10, 0.9 * (s.difficulty + D_DELTA[outcome]) + 0.5));
    s.last = Math.max(s.last, at);
    s.reps++;
  }
  const rank = RANK[mode];
  if (ok && rank !== undefined && (s.best === null || rank > RANK[s.best]!)) s.best = mode;
  return s;
}

// Recall probability after `days` with stability `s`.
export function recall(s: number, days: number): number {
  return 1 / (1 + days / (CURVE * s));
}

export function recallNow(s: State, now = Date.now()): number {
  return recall(s.stability, Math.max(0, now - s.last) / DAY);
}

// Mastery level 0..5: 0 unseen, 1 seen, 2 learning, 3 known, 4 solid, 5 mastered.
export function mastery(s: State | null): number {
  if (s === null) return 0;
  if (s.best === null || s.stability < 0.5) return 1;
  if (s.stability < 3) return 2;
  if (s.stability < 21) return 3;
  if (s.stability >= 90 && RANK[s.best]! >= 2) return 5;
  return 4;
}

// A hinted answer counts at most as hard.
export function capHinted(o: Outcome, hinted: boolean): Outcome {
  return hinted && (o === 'good' || o === 'easy') ? 'hard' : o;
}
