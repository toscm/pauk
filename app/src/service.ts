// macOS: pauk as a login service (launchd) plus a menu bar item.
//   pauk service install    start pauk now and at every login, restart it if it dies;
//                           build and start the menu bar item (macos/PaukMenu.swift)
//   pauk service uninstall  stop both and remove them
//   pauk restart            restart the service (the menu and Ctrl+Option+Cmd+P do the same)

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { HOME } from './config.ts';

export const SERVER = 'local.pauk.server';
const MENU = 'local.pauk.menu';
const AGENTS = path.join(os.homedir(), 'Library', 'LaunchAgents');
const domain = `gui/${process.getuid!()}`;
const plist = (label: string) => path.join(AGENTS, `${label}.plist`);
const MENU_BIN = path.join(HOME, 'bin', 'pauk-menu');
const MENU_SRC = path.join(import.meta.dirname, '..', 'macos', 'PaukMenu.swift');

function agent(label: string, args: string[], env: Record<string, string> = {}): string {
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const strings = (xs: string[]) => xs.map((x) => `<string>${esc(x)}</string>`).join('');
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${label}</string>
  <key>ProgramArguments</key><array>${strings(args)}</array>
  <key>EnvironmentVariables</key><dict>${Object.entries(env).map(([k, v]) => `<key>${k}</key><string>${esc(v)}</string>`).join('')}</dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>${esc(path.join(HOME, `${label.split('.').at(-1)}.log`))}</string>
  <key>StandardErrorPath</key><string>${esc(path.join(HOME, `${label.split('.').at(-1)}.log`))}</string>
</dict></plist>
`;
}

function load(label: string, content: string): void {
  fs.mkdirSync(AGENTS, { recursive: true });
  unload(label);
  fs.writeFileSync(plist(label), content);
  execFileSync('launchctl', ['bootstrap', domain, plist(label)]);
}

function unload(label: string): void {
  try {
    execFileSync('launchctl', ['bootout', `${domain}/${label}`], { stdio: 'ignore' });
  } catch { /* was not loaded */ }
  // bootout returns before the old instance is gone; bootstrap fails until it is
  for (let i = 0; i < 50; i++) {
    try {
      execFileSync('launchctl', ['print', `${domain}/${label}`], { stdio: 'ignore' });
    } catch {
      return;
    }
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
  }
}

export function service(sub: string | undefined): void {
  if (process.platform !== 'darwin') throw new Error('pauk service is for macOS (launchd); elsewhere use systemd or run `pauk start`');
  if (sub === 'install') {
    // the same node and the same cli.ts this command runs with, so code changes take effect on restart
    const env: Record<string, string> = { PATH: `${path.dirname(process.execPath)}:/usr/bin:/bin` };
    if (process.env.PAUK_HOME) env.PAUK_HOME = HOME;
    load(SERVER, agent(SERVER, [process.execPath, '--disable-warning=ExperimentalWarning', fs.realpathSync(path.join(import.meta.dirname, 'cli.ts')), 'start'], env));
    console.log(`pauk runs as the login service ${SERVER} (log: ${path.join(HOME, 'server.log')})`);
    fs.mkdirSync(path.dirname(MENU_BIN), { recursive: true });
    console.log('building the menu bar item …');
    execFileSync('swiftc', ['-O', '-o', MENU_BIN, MENU_SRC], { stdio: 'inherit' });
    load(MENU, agent(MENU, [MENU_BIN], { PAUK_HOME: HOME }));
    console.log(`the pauk menu bar item runs as ${MENU}; Ctrl+Option+Cmd+P restarts pauk`);
  } else if (sub === 'uninstall') {
    for (const label of [MENU, SERVER]) {
      unload(label);
      fs.rmSync(plist(label), { force: true });
    }
    fs.rmSync(MENU_BIN, { force: true });
    console.log('removed the pauk service and the menu bar item');
  } else {
    throw new Error('usage: pauk service install | uninstall');
  }
}

export function restart(): void {
  try {
    execFileSync('launchctl', ['kickstart', '-k', `${domain}/${SERVER}`]);
    console.log('pauk restarted');
  } catch {
    throw new Error('the pauk service is not installed: run `pauk service install` (or `pauk start` in a terminal)');
  }
}
