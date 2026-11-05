// The knowledge profile: items joined with the states from the log, and
// "what to practise next" (ported from the PHP API's Profile.php).

import fs from 'node:fs';
import path from 'node:path';
import { inSubject, type Item, type Knowledge } from './knowledge.ts';
import type { Log } from './log.ts';
import { mastery, recallNow } from './memory.ts';
import { norm } from './text.ts';

const TARGET = 0.9;   // review an item once its recall drops below 90 %

export function stateView(log: Log, ref: string) {
  const s = log.states.get(ref) ?? null;
  return {
    mastery: mastery(s),
    recall: s && s.reps > 0 ? Math.round(recallNow(s) * 100) / 100 : null,
    reps: s?.reps ?? 0,
    lapses: s?.lapses ?? 0,
    best_mode: s?.best ?? null,
    last_seen: s ? new Date(s.last).toISOString().slice(0, 10) : null,
    flag: log.flags.get(ref) ?? null,
  };
}

export function itemView(k: Knowledge, log: Log, item: Item, full = false) {
  const base = { ref: item.ref, kind: item.kind, label: item.label, gloss: item.gloss, state: stateView(log, item.ref) };
  if (!full) return base;
  return {
    ...base,
    body: item.body, mnemonic: item.mnemonic || undefined, anecdote: item.anecdote || undefined,
    subjects: item.subjects, links: item.links, notes: log.notes.get(item.ref) ?? [],
    cards: item.cards.map((c) => ({ type: c.type, q: c.q, answer: c.answer, wrong: c.wrong, pairs: c.pairs, items: c.items })),
    history: log.history(k, item.ref).map((l) => ({ t: l.t, type: l.type, mode: l.mode, outcome: l.items?.[item.ref] })),
  };
}

export function summary(k: Knowledge, log: Log, subject?: string) {
  const byMastery = [0, 0, 0, 0, 0, 0];
  let due = 0;
  let total = 0;
  let failing = 0;   // tested, but not even "learning" yet (the red ones)
  for (const item of k.items.values()) {
    if (!inSubject(item, subject)) continue;
    total++;
    const v = stateView(log, item.ref);
    byMastery[v.mastery]++;
    if (v.mastery === 1 && v.best_mode !== null) failing++;
    if (v.recall !== null && v.recall < TARGET && v.flag !== 'suspended') due++;
  }
  return { subject: subject ?? '(all)', items: total, due, by_mastery: byMastery, failing, levels: 'unseen, seen, learning, known, solid, mastered' };
}

// Due items first (lowest recall, weighted by priority), then unseen
// items whose prerequisites are known.
export function next(k: Knowledge, log: Log, subject: string | undefined, n = 10) {
  const review: { score: number; item: Item; reason: string }[] = [];
  const fresh: { item: Item }[] = [];
  for (const item of k.items.values()) {
    if (!inSubject(item, subject) || log.flags.get(item.ref) === 'suspended') continue;
    const focus = log.flags.get(item.ref) === 'focus' ? 2 : 1;
    const s = log.states.get(item.ref);
    if (s && s.reps > 0) {
      const r = recallNow(s);
      const target = s.lapses >= 2 ? 0.95 : TARGET;
      if (r < target) review.push({ score: (target - r) * (0.5 + item.priority / 100) * focus, item, reason: `due: R=${r.toFixed(2)}` });
      continue;
    }
    if (s) continue;   // introduced, never answered: the teacher should test it, not introduce it again
    const blocked = item.links.some((l) => l.rel === 'requires' && mastery(log.states.get(l.to) ?? null) < 3);
    if (!blocked) fresh.push({ item: { ...item, priority: item.priority * focus } });
  }
  review.sort((a, b) => b.score - a.score);
  fresh.sort((a, b) => b.item.priority - a.item.priority || (a.item.level ?? 99) - (b.item.level ?? 99));   // ties keep the order of the files
  const introduced = [...log.states].filter(([ref, s]) => s.reps === 0 && k.items.has(ref) && inSubject(k.items.get(ref)!, subject));
  return {
    review: review.slice(0, n).map((r) => ({ ...itemView(k, log, r.item), reason: r.reason })),
    introduced_untested: introduced.slice(0, n).map(([ref]) => ref),
    new: fresh.slice(0, n).map((f) => itemView(k, log, k.items.get(f.item.ref)!)),
  };
}

export function search(k: Knowledge, log: Log, q: string | undefined, subject: string | undefined, n = 25) {
  const needle = q ? norm(q) : '';
  const out = [];
  for (const item of k.items.values()) {
    if (!inSubject(item, subject)) continue;
    const hay = norm(`${item.ref} ${item.label} ${item.gloss} ${item.aliases.join(' ')}`);
    if (needle && !hay.includes(needle) && !norm(item.body).includes(needle)) continue;
    out.push(itemView(k, log, item));
    if (out.length >= n) break;
  }
  return out;
}

// The subject tree with item counts for the start page, with the learner's
// favorites and how much they used each subject lately ('' is everything).
export function subjects(k: Knowledge, log: Log, favorites: string[] = [], used = new Map<string, Usage>()) {
  const all = new Set<string>();
  for (const s of k.subjects) s.split('/').forEach((_, i, parts) => all.add(parts.slice(0, i + 1).join('/')));
  return ['', ...[...all].sort()].map((p) => ({
    ...summary(k, log, p || undefined), path: p, order: k.order.get(p) ?? null,
    favorite: favorites.includes(p), recent: Math.round((used.get(p)?.score ?? 0) * 100) / 100, last: used.get(p)?.last ?? null,
  }));
}

// "Frecency" from the session transcripts: every session adds 1 to its
// subject, and that 1 halves with every week since.
export interface Usage { score: number; last: string }
export function usage(sessionsDir: string, now = Date.now()): Map<string, Usage> {
  const out = new Map<string, Usage>();
  if (!fs.existsSync(sessionsDir)) return out;
  for (const f of fs.readdirSync(sessionsDir).filter((f) => f.endsWith('.jsonl'))) {
    const first = fs.readFileSync(path.join(sessionsDir, f), 'utf8').split('\n', 1)[0];
    try {
      const e = JSON.parse(first);
      if (e.type !== 'start') continue;
      const p = e.goal?.subject ?? '';
      const u = out.get(p) ?? { score: 0, last: e.t };
      u.score += 0.5 ** ((now - Date.parse(e.t)) / (7 * 86400e3));
      if (e.t > u.last) u.last = e.t;
      out.set(p, u);
    } catch { /* an unreadable transcript counts as nothing */ }
  }
  return out;
}

// The items filed directly in a subject (by their file or by `also`), in
// file order, each with a short plain-text name like a file name.
export function itemsIn(k: Knowledge, log: Log, subject: string) {
  return [...k.items.values()].filter((i) => i.subjects.includes(subject)).map((i) => {
    const st = stateView(log, i.ref);
    return { ref: i.ref, name: shortName(i.label), mastery: st.mastery, tested: st.best_mode !== null, recall: st.recall, due: st.recall !== null && st.recall < TARGET };
  });
}

export function shortName(md: string, max = 50): string {
  const text = md.replace(/!\[[^\]]*\]\([^)]*\)/g, '🖼').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[*_`#>]+/g, '').replace(/\s+/g, ' ').trim();
  return text.length > max ? text.slice(0, max - 1).trimEnd() + '…' : text;
}
