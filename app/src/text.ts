// Text matching and item keys, ported from the PHP API (Text.php, Norm.php).
// Grading must stay identical across versions: the grader name in the log
// (text@2) says which rules judged an answer.

const DIACRITICS: Record<string, string> = {
  à: 'a', á: 'a', â: 'a', ã: 'a', ä: 'a', å: 'a', è: 'e', é: 'e', ê: 'e', ë: 'e',
  ì: 'i', í: 'i', î: 'i', ï: 'i', ò: 'o', ó: 'o', ô: 'o', õ: 'o', ö: 'o',
  ù: 'u', ú: 'u', û: 'u', ü: 'u', ç: 'c', ñ: 'n', ý: 'y', ÿ: 'y', æ: 'ae', œ: 'oe', ß: 'ss',
};

const GREEK_TONOS: Record<string, string> = {
  ά: 'α', έ: 'ε', ή: 'η', ί: 'ι', ό: 'ο', ύ: 'υ', ώ: 'ω', ϊ: 'ι', ϋ: 'υ', ΐ: 'ι', ΰ: 'υ',
};

const GREEK_NAMES: Record<string, string> = {
  α: 'alpha', β: 'beta', γ: 'gamma', δ: 'delta', ε: 'epsilon', ζ: 'zeta', η: 'eta', θ: 'theta',
  ι: 'iota', κ: 'kappa', λ: 'lambda', μ: 'mu', ν: 'nu', ξ: 'xi', ο: 'omicron', π: 'pi', ρ: 'rho',
  σ: 'sigma', ς: 'sigma', τ: 'tau', υ: 'upsilon', φ: 'phi', χ: 'chi', ψ: 'psi', ω: 'omega',
};

const GREEK_TRANSLIT: Record<string, string> = {
  α: 'a', β: 'v', γ: 'g', δ: 'd', ε: 'e', ζ: 'z', η: 'i', θ: 'th', ι: 'i', κ: 'k', λ: 'l', μ: 'm',
  ν: 'n', ξ: 'x', ο: 'o', π: 'p', ρ: 'r', σ: 's', ς: 's', τ: 't', υ: 'y', φ: 'f', χ: 'ch', ψ: 'ps', ω: 'o',
};

// Swapping one vowel for another changes the word in the languages pauk
// teaches (fare/faro, per/por), so it costs two edits (docs/architecture.md).
const VOWELS = new Set('aeiouαεηιουωάέήίόύώϊϋΐΰ');

const fold = (s: string, table: Record<string, string>) => [...s].map((c) => table[c] ?? c).join('');

// Lowercase, fold Latin diacritics, punctuation and symbols to spaces.
export function normalize(s: string): string {
  return fold(s.trim().toLowerCase(), DIACRITICS)
    .replace(/[\p{P}\p{S}]+/gu, ' ')
    .replace(/\s+/gu, ' ')
    .trim();
}

// Levenshtein distance over code points in which a vowel replaced by
// another vowel costs two edits.
export function typoDistance(a: string, b: string): number {
  const sa = [...a];
  const sb = [...b];
  let prev = Array.from({ length: sb.length + 1 }, (_, j) => j);
  sa.forEach((ca, i) => {
    const cur = [i + 1];
    sb.forEach((cb, j) => {
      const cost = ca === cb ? 0 : VOWELS.has(ca) && VOWELS.has(cb) ? 2 : 1;
      cur[j + 1] = Math.min(prev[j + 1] + 1, cur[j] + 1, prev[j] + cost);
    });
    prev = cur;
  });
  return prev[sb.length];
}

export type Match = 'exact' | 'typo' | 'wrong';

// Grade a free-text answer: exact after normalization, a typo within
// one edit per 8 characters (answers under 4 characters must be exact).
export function gradeText(answer: string, accepted: string[]): Match {
  const a = normalize(answer);
  if (a === '') return 'wrong';
  const norms = accepted.map(normalize);
  if (norms.includes(a)) return 'exact';
  for (const n of norms) {
    const len = [...n].length;
    if (len >= 4 && typoDistance(a, n) <= Math.max(1, Math.floor(len / 8))) return 'typo';
  }
  return 'wrong';
}

// A label for comparison: Markdown images, links and parentheticals removed.
export function norm(label: string): string {
  const s = label
    .replace(/!\[[^\]]*\]\([^)]*\)/gu, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/gu, '$1')
    .replace(/\([^)]*\)/gu, ' ');
  return normalize(fold(s.toLowerCase(), GREEK_TONOS));
}

// ASCII key slug of a label (`α` -> `alpha`, `La farfalla` -> `la-farfalla`).
export function slug(label: string): string {
  const s = norm(label);
  if (GREEK_NAMES[s]) return GREEK_NAMES[s];
  return fold(s, GREEK_TRANSLIT).replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 120);
}

export const KINDS = ['word', 'form', 'phrase', 'rule', 'symbol', 'term', 'fact', 'paper', 'skill', 'other'];
const KEY_RE = /^[a-z0-9]+(-[a-z0-9]+)*(\.[a-z0-9]+(-[a-z0-9]+)*)*$/;
const SPACE_RE = /^[a-z][a-z0-9-]{0,15}$/;

// Null if `space/key` is a valid item reference, else the reason.
export function refError(ref: string): string | null {
  const [space, key, extra] = ref.split('/');
  if (extra !== undefined || key === undefined) return `"${ref}" must be space/key`;
  if (!SPACE_RE.test(space)) return `space "${space}" must be a short lowercase slug`;
  if (!KEY_RE.test(key) || key.length > 191) return `key "${key}" must be lowercase slugs separated by dots, e.g. essere.pres.1sg`;
  return null;
}
