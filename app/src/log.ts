// The learning log: one JSON line per observation in
// <user>/log/<device>/YYYY-MM.jsonl, append-only. Each machine writes only
// its own folder, so synced copies never conflict; the lines of all
// devices (and of older logs directly in log/) are read and sorted by time.
// Item states, flags and notes are recomputed from them (docs/files.md).

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { resolve, type Knowledge } from './knowledge.ts';
import { step, type Mode, type Outcome, type State } from './memory.ts';

export interface Line {
  id: string;
  t: string;                        // ISO time, UTC, millisecond precision
  type: 'answer' | 'introduce' | 'amend' | 'flag' | 'note';
  session?: string;
  mode?: Mode;
  items?: Record<string, Outcome | null>;   // ref -> outcome (null: no evidence)
  ex?: unknown;                     // the exercise as shown, with its key
  resp?: unknown;                   // the learner's response
  grader?: string;                  // text@2, mc@1, match@1, teacher, self
  of?: string;                      // amend: id of the corrected line
  reason?: string;
  item?: string;                    // flag, note
  status?: 'active' | 'focus' | 'suspended';
  text?: string;
}

export class Log {
  lines: Line[] = [];
  states = new Map<string, State>();
  flags = new Map<string, 'focus' | 'suspended'>();
  notes = new Map<string, string[]>();
  dir: string;   // where this device appends

  constructor(dir: string, device?: string) {
    const root = path.join(dir, 'log');
    this.dir = device ? path.join(root, device) : root;
    fs.mkdirSync(this.dir, { recursive: true });
    const files = fs.readdirSync(root, { recursive: true, encoding: 'utf8' }).filter((f) => f.endsWith('.jsonl')).sort();
    for (const f of files) {
      for (const [i, raw] of fs.readFileSync(path.join(root, f), 'utf8').split('\n').entries()) {
        if (!raw.trim()) continue;
        try {
          this.lines.push(JSON.parse(raw));
        } catch {
          console.warn(`${f}:${i + 1}: not JSON, skipped`);
        }
      }
    }
    this.lines.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));
  }

  // Recompute everything from the lines (at startup and after an amendment).
  replay(k: Knowledge): this {
    this.states.clear();
    this.flags.clear();
    this.notes.clear();
    const amended = new Map(this.lines.filter((l) => l.type === 'amend').map((l) => [l.of!, l.items!]));
    for (const l of this.lines) this.apply(k, l, amended.get(l.id));
    return this;
  }

  private apply(k: Knowledge, l: Line, amended?: Record<string, Outcome | null>): void {
    const ref = (r: string) => resolve(k, r) ?? r;   // unknown refs keep their evidence
    if (l.type === 'answer' || l.type === 'introduce') {
      const at = Date.parse(l.t);
      for (const [r, o] of Object.entries(amended ?? l.items ?? {})) {
        const prev = this.states.get(ref(r)) ?? null;
        if (l.type === 'introduce') this.states.set(ref(r), step(prev, 'introduce', null, at));
        else if (o !== null) this.states.set(ref(r), step(prev, l.mode ?? 'recall', o, at));
      }
    } else if (l.type === 'flag' && l.item) {
      if (l.status === 'active') this.flags.delete(ref(l.item));
      else this.flags.set(ref(l.item), l.status!);
    } else if (l.type === 'note' && l.item && l.text) {
      this.notes.set(ref(l.item), [...(this.notes.get(ref(l.item)) ?? []), l.text]);
    }
  }

  // Append a new observation and apply it.
  add(k: Knowledge, fields: Omit<Line, 'id' | 't'>): Line {
    const line: Line = { id: crypto.randomBytes(5).toString('hex'), t: new Date().toISOString(), ...fields };
    fs.appendFileSync(path.join(this.dir, `${line.t.slice(0, 7)}.jsonl`), JSON.stringify(line) + '\n');
    this.lines.push(line);
    if (line.type === 'amend') this.replay(k);
    else this.apply(k, line);
    return line;
  }

  // The last observations of one item, newest first.
  history(k: Knowledge, ref: string, n = 8): Line[] {
    const refs = new Set([ref, ...(k.items.get(ref)?.aliases ?? [])]);
    const out: Line[] = [];
    for (let i = this.lines.length - 1; i >= 0 && out.length < n; i--) {
      const l = this.lines[i];
      if (Object.keys(l.items ?? {}).some((r) => refs.has(r)) || (l.item && refs.has(l.item))) out.push(l);
    }
    return out;
  }
}
