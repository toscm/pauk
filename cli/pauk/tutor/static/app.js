// Entry point: the learner chat (default) or the read-only observer
// view (`?observer=<key>`). Loads the transcript, follows new events
// over SSE, and keeps header, side panel and composer in sync.

import { eventsUrl, get, learnerKey, observerKey, post } from './api.js';
import { touchedList } from './cards.js';
import { runObserver } from './observer.js';
import { profileDialog } from './profile.js';
import { reportDialog } from './report.js';
import { settingsDialog } from './settings.js';
import { startCard } from './start.js';
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

if (observerKey) runObserver(); else boot();

async function boot() {
  if (!learnerKey) {
    $('transcript').append(h('p', {class: 'notice'}, 'This link has no learner key (#k=…). Open the link that pauk printed.'));
    return;
  }
  const report = reportDialog();
  const settings = settingsDialog();
  const profile = profileDialog();
  transcript = new Transcript($('transcript'), {onReport: (seq) => report.open(seq), onChange});

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
    $('status-text').textContent = 'Could not load the session.';
    return;
  }
  applyStatus(state);
  for (const ev of state.events) transcript.add(ev, false);
  lastSeq = state.last_seq;
  $('transcript').lastElementChild?.scrollIntoView({block: 'end'});
  if (!state.goal && !state.ended) $('start-slot').replaceChildren(startCard());
  render();
  if (!host.ended) connect();
  setInterval(pollStatus, 10000);
  setInterval(renderTimer, 1000);
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
    applyStatus(await get('learner/status'));
    host.unreachable = false;
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
  }
  render();
}

// --- rendering ------------------------------------------------------------------

function render() {
  renderStatus();
  renderTimer();
  const g = host.goal;
  $('side-goal').textContent = g ? `${g.dirs.join(', ') || 'all subjects'} · ${g.mode} · ${g.minutes} min` : 'No goal yet.';
  $('side-touched').replaceChildren(touchedList([...touched.values()]));
  $('btn-end').disabled = host.ended;
  updateComposer();
}

function renderStatus() {
  let text;
  let busy = false;
  let restart = false;
  if (host.ended) text = 'Session ended';
  else if (host.unreachable) text = 'Session host unreachable';
  else if (!host.connected && (host.everConnected || host.agentDied)) {
    text = 'Teacher disconnected';
    restart = true;
  } else if (transcript.awaiting && (host.connected || transcript.teacherSeen)) {
    text = 'Teacher is thinking…';
    busy = true;
  } else if (!transcript.teacherSeen) {
    text = 'Waiting for teacher…';
    busy = true;
  } else text = 'Teacher connected';
  $('status-text').textContent = text;
  $('status').classList.toggle('busy', busy);
  $('btn-restart').hidden = !restart;
  $('side-status').textContent = text;
}

function renderTimer() {
  let text = '';
  if (host.ended) text = 'ended';
  else if (host.goal && host.goalStartedAt) {
    const left = host.goal.minutes * 60 - (Date.now() / 1000 + host.offset - host.goalStartedAt);
    text = left >= 0 ? `${clock(left)} left` : `${clock(-left)} over`;
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
  $('send').textContent = target ? 'Answer' : 'Send';
  $('input').placeholder = host.ended ? 'The session has ended.'
    : target ? 'Your answer (Enter to submit)' : 'Message the teacher (Enter to send, Shift+Enter for a new line)';
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
  if (!confirm('End the session? The teacher will wrap up with a summary.')) return;
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
    toast('Restarting the teacher…');
  } catch (e) {
    showError(e);
  }
}
