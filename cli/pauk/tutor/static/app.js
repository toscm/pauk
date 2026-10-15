// Entry point: the learner chat (default) or the read-only observer
// view (`?observer=<key>`). Loads the transcript, follows new events
// over SSE, and keeps header, side panel and composer in sync. The UI
// language follows the learner's tutor.language setting (i18n.js).

import { eventsUrl, get, learnerKey, observerKey, post } from './api.js';
import { touchedList } from './cards.js';
import { setLanguage, t } from './i18n.js';
import { runObserver } from './observer.js';
import { profileDialog } from './profile.js';
import { reportDialog } from './report.js';
import { settingsDialog } from './settings.js';
import { goalText, startCard } from './start.js';
import { Transcript } from './transcript.js';
import { clock, h, showError, toast, typing } from './ui.js';

const $ = (id) => document.getElementById(id);

const host = {
  goal: null, ended: false, goalStartedAt: null, offset: 0,   // offset: server clock - local clock (s)
  connected: false, everConnected: false, agentDied: false, unreachable: false,
};
const touched = new Map();   // ref -> {ref, label_md, before, now}
let transcript;
let lastSeq = 0;
let report;
let settings;
let profile;

if (observerKey) runObserver(); else boot();

async function boot() {
  if (!learnerKey) {
    $('transcript').append(h('p', {class: 'notice'}, t('app.no_key')));
    return;
  }
  dialogs();
  transcript = new Transcript($('transcript'), {pane: $('task-pane'), list: $('side-tasks'),
                                                onReport: (seq) => report.open(seq), onChange});

  $('btn-profile').addEventListener('click', () => profile.open(host.goal?.dirs?.[0]));
  $('btn-settings').addEventListener('click', () => settings.open());
  $('btn-report').addEventListener('click', () => report.open());
  $('btn-end').addEventListener('click', endSession);
  $('btn-restart').addEventListener('click', restartTeacher);
  $('composer').addEventListener('submit', sendComposer);
  $('input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      $('composer').requestSubmit();
    }
  });
  $('input').addEventListener('focus', updateComposer);
  $('ask-teacher').addEventListener('change', updateComposer);
  document.addEventListener('exercisechange', updateComposer);
  document.addEventListener('keydown', (e) => {
    if (e.key === '!' && !typing() && !document.querySelector('dialog[open]')) {
      e.preventDefault();
      report.open();
    }
  });

  let state;
  try {
    state = await get('learner/state');
  } catch (e) {
    showError(e);
    $('status-text').textContent = t('app.load_failed');
    return;
  }
  if (await setLanguage(state.settings?.['tutor.language'])) dialogs();
  applyStatus(state);
  for (const ev of state.events) transcript.add(ev, false);
  lastSeq = state.last_seq;
  transcript.renderTasks();
  transcript.scrollToEnd();
  if (!state.goal && !state.ended) $('start-slot').replaceChildren(startCard());
  render();
  if (!host.ended) connect();
  setInterval(pollStatus, 10000);
  setInterval(renderTimer, 1000);
}

// The dialogs keep their texts: built anew when the language changes.
function dialogs() {
  for (const dialog of document.querySelectorAll('body > dialog')) dialog.remove();
  report = reportDialog();
  settings = settingsDialog();
  profile = profileDialog();
}

// A settings change may switch the UI language: re-render everything.
async function useLanguage(values) {
  if (!values || !(await setLanguage(values['tutor.language']))) return;
  dialogs();
  transcript.rebuild();
  if ($('start-slot').firstChild) $('start-slot').replaceChildren(startCard());
  render();
}

// --- server push ------------------------------------------------------------

function connect() {
  const source = new EventSource(eventsUrl(lastSeq));
  source.onmessage = (message) => {
    const ev = JSON.parse(message.data);
    lastSeq = Math.max(lastSeq, ev.seq);
    transcript.add(ev, true);
  };
  source.addEventListener('ended', () => {
    source.close();
    host.ended = true;
    render();
  });
  source.onerror = () => {
    source.close();
    if (!host.ended) setTimeout(connect, 2000);
  };
}

async function pollStatus() {
  if (host.ended) return;
  try {
    const status = await get('learner/status');
    applyStatus(status);
    host.unreachable = false;
    await useLanguage(status.settings);
  } catch {
    host.unreachable = true;
  }
  render();
}

function applyStatus(s) {
  host.goal = s.goal;
  host.ended = host.ended || s.ended;
  host.goalStartedAt = s.goal_started_at;
  host.offset = s.now - Date.now() / 1000;
  host.connected = s.teacher_connected;
  host.everConnected ||= s.teacher_connected;
  if (s.agent_running) host.agentDied = false;
  touched.clear();
  for (const t of s.touched) touched.set(t.ref, t);
}

// Replayed events (live = false) only teach what the status snapshot
// cannot: whether a teacher was ever there and whether the agent died.
function onChange(ev, live) {
  if (ev.from === 'teacher' || ev.teacher_connected) host.everConnected = true;
  if (ev.type === 'status' && 'agent_running' in ev) host.agentDied = !ev.agent_running;
  if (!live) return;
  if (ev.from === 'teacher') host.connected = true;
  switch (ev.type) {
    case 'status':
      if ('teacher_connected' in ev) host.connected = ev.teacher_connected;
      break;
    case 'start':
      host.goal = ev.goal;
      host.goalStartedAt = ev.at;
      $('start-slot').replaceChildren();
      break;
    case 'level_change':
      for (const c of ev.changes) {
        const before = touched.get(c.ref)?.before ?? c.before;
        touched.set(c.ref, {ref: c.ref, label_md: c.label_md, before, now: c.now});
      }
      break;
    case 'ended':
      host.ended = true;
      break;
    case 'settings_changed':
      useLanguage(ev.settings);
      break;
  }
  render();
}

// --- rendering ------------------------------------------------------------------

function render() {
  renderStatus();
  renderTimer();
  const g = host.goal;
  $('side-goal').textContent = g ? goalText(g) : t('app.no_goal');
  $('side-touched').replaceChildren(touchedList([...touched.values()]));
  $('btn-end').disabled = host.ended;
  updateComposer();
}

function renderStatus() {
  let text;
  let busy = false;
  let restart = false;
  if (host.ended) text = t('app.status.ended');
  else if (host.unreachable) text = t('app.status.unreachable');
  else if (!host.connected && (host.everConnected || host.agentDied)) {
    text = t('app.status.disconnected');
    restart = true;
  } else if (transcript.awaiting && (host.connected || transcript.teacherSeen)) {
    text = t('app.status.thinking');
    busy = true;
  } else if (!transcript.teacherSeen) {
    text = t('app.status.waiting');
    busy = true;
  } else text = t('app.status.connected');
  $('status-text').textContent = text;
  $('status').classList.toggle('busy', busy);
  $('btn-restart').hidden = !restart;
  $('side-status').textContent = text;
}

function renderTimer() {
  let text = '';
  if (host.ended) text = t('app.timer.ended');
  else if (host.goal && host.goalStartedAt) {
    const left = host.goal.minutes * 60 - (Date.now() / 1000 + host.offset - host.goalStartedAt);
    text = left >= 0 ? t('app.timer.left', {time: clock(left)}) : t('app.timer.over', {time: clock(-left)});
  }
  $('timer').textContent = text;
  $('side-timer').textContent = text || '–';
}

function updateComposer() {
  const answerable = host.ended ? null : transcript.answerTarget();
  const target = $('ask-teacher').checked ? null : answerable;
  $('ask-toggle').hidden = !answerable;
  $('input').disabled = host.ended;
  $('send').disabled = host.ended;
  $('send').textContent = target ? t('app.answer') : t('app.send');
  $('input').placeholder = host.ended ? t('app.placeholder.ended')
    : target ? t('app.placeholder.answer') : t('app.placeholder.message');
}

// --- actions ---------------------------------------------------------------------

async function sendComposer(e) {
  e.preventDefault();
  const input = $('input');
  const text = input.value.trim();
  if (!text || host.ended) return;
  const target = $('ask-teacher').checked ? null : transcript.answerTarget();
  $('send').disabled = true;
  try {
    if (target) {
      if (!(await target.submitText(text))) return;
    } else {
      await post('learner/message', {text});
    }
    input.value = '';
    $('ask-teacher').checked = false;
  } catch (error) {
    showError(error);
  } finally {
    updateComposer();
  }
}

async function endSession() {
  if (!confirm(t('app.confirm_end'))) return;
  try {
    await post('learner/end');
    $('btn-end').disabled = true;
  } catch (e) {
    showError(e);
  }
}

async function restartTeacher() {
  try {
    await post('learner/restart-teacher');
    toast(t('app.restarting'));
  } catch (e) {
    showError(e);
  }
}
