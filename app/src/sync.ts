// Syncing the progress folder (config.yaml `progress`) through git.
//
// Nothing to configure: pauk syncs the folder when it is a git repository.
// It commits what it wrote, and when the branch has an upstream it also
// pulls (rebase) and pushes. pauk syncs at startup, before and after each
// session, every few minutes and when it stops; `pauk sync` syncs by hand.
//
// Conflicts are avoided rather than resolved: every device appends its log
// lines to its own log/<device>/ folder, the other append-only files merge
// by keeping both sides' lines (.gitattributes, written here), and for
// the rest (settings.yaml) this device's version wins.

import fs from 'node:fs';
import path from 'node:path';
import { execFile } from 'node:child_process';

const ATTRIBUTES = `# Written by pauk (src/sync.ts).
# pauk writes LF on every system; no CRLF conversion (core.autocrlf on Windows).
* text eol=lf
# Append-only files merge by keeping the lines of both sides.
*.jsonl merge=union
items.yaml merge=union
`;
const EVERY = 5 * 60 * 1000;

export interface SyncResult {
  committed: boolean;   // pauk committed new changes
  pulled: boolean;      // changes of other devices arrived
  pushed: boolean;
  remote: string | null;   // the upstream, e.g. origin/main; null: commit only
  error?: string;
}

export class Sync {
  dir: string;
  device: string;
  private queue: Promise<unknown> = Promise.resolve();
  private timer?: NodeJS.Timeout;

  constructor(dir: string, device: string) {
    this.dir = dir;
    this.device = device;
  }

  // the top of a git work tree (a progress folder inside another repository is not synced)
  get enabled(): boolean {
    return fs.existsSync(path.join(this.dir, '.git'));
  }

  // One sync at a time; a call while one runs waits for it.
  run(reason: string): Promise<SyncResult> {
    const next = this.queue.then(() => this.once(reason));
    this.queue = next.catch(() => {});
    return next;
  }

  // Sync every few minutes; `after` sees each result (e.g. to reload).
  every(after: (r: SyncResult) => void, ms = EVERY): void {
    if (!this.enabled) return;
    this.timer = setInterval(() => this.run('periodic').then(after, () => {}), ms);
    this.timer.unref();
  }

  stop(): void {
    clearInterval(this.timer);
  }

  private async once(reason: string): Promise<SyncResult> {
    const r: SyncResult = { committed: false, pulled: false, pushed: false, remote: null };
    if (!this.enabled) return r;
    try {
      const attributes = path.join(this.dir, '.gitattributes');
      if (!fs.existsSync(attributes)) fs.writeFileSync(attributes, ATTRIBUTES);
      if ((await this.git('status', '--porcelain')).trim()) {
        await this.git('add', '--all');
        await this.git(...(await this.identity()), 'commit', '--quiet', '-m', `${reason} (${this.device})`);
        r.committed = true;
      }
      r.remote = await this.upstream();
      if (!r.remote) {
        // a fresh clone of an empty repository: the first push sets the upstream
        if (!r.committed || !(await this.git('remote')).split(/\s+/).includes('origin')) return r;
        await this.git('push', '--quiet', '--set-upstream', 'origin', 'HEAD');
        return { ...r, pushed: true, remote: await this.upstream() };
      }
      const before = await this.git('rev-parse', 'HEAD');
      try {
        // in a rebase "theirs" is the commit being replayed: this device's version wins
        await this.git('pull', '--quiet', '--rebase', '--autostash', '-X', 'theirs');
      } catch (err) {
        await this.git('rebase', '--abort').catch(() => {});
        throw err;
      }
      r.pulled = (await this.git('rev-parse', 'HEAD')) !== before;
      if (Number(await this.git('rev-list', '--count', '@{upstream}..HEAD')) > 0) {
        await this.git('push', '--quiet');
        r.pushed = true;
      }
    } catch (err) {
      r.error = err instanceof Error ? err.message.trim() : String(err);
    }
    return r;
  }

  private upstream(): Promise<string | null> {
    return this.git('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}').then((u) => u || null, () => null);
  }

  // a fallback author for machines without git user.name / user.email
  private async identity(): Promise<string[]> {
    const email = await this.git('config', 'user.email').catch(() => '');
    return email.trim() ? [] : ['-c', 'user.name=pauk', '-c', `user.email=pauk@${this.device}`];
  }

  private git(...args: string[]): Promise<string> {
    return new Promise((resolve, reject) => {
      execFile('git', args, {
        cwd: this.dir, timeout: 60_000, windowsHide: true,
        env: { ...process.env, GIT_TERMINAL_PROMPT: '0' },   // fail instead of waiting for a password
      }, (err, stdout, stderr) => (err ? reject(new Error(`git ${args.join(' ')}: ${stderr || err.message}`)) : resolve(stdout.trim())));
    });
  }
}

// One line for the console.
export function describe(r: SyncResult, dir: string): string {
  if (r.error) return `progress sync failed (${dir}): ${r.error}`;
  if (!r.remote) return `progress committed locally in ${dir} (no upstream to push to)`;
  const did = [r.committed && 'committed', r.pulled && 'pulled', r.pushed && 'pushed'].filter(Boolean).join(', ');
  return `progress synced with ${r.remote}${did ? `: ${did}` : ': up to date'}`;
}
