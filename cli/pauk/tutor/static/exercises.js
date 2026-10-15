// Exercise widgets (mc, match, text, open, recall) and drills.
// A widget only sends requests; what it shows after answering comes
// from the transcript events (answered, graded, hint, reveal, ...),
// so a reload renders exactly the same as the live session.

import { post } from './api.js';
import { t } from './i18n.js';
import { md, plain } from './md.js';
import { h, showError, toast } from './ui.js';

function mark(correct, partial = false) {
  const [cls, sign, label] = correct ? ['ok', '✓', t('ex.mark.correct')] : partial ? ['partial', '◐', t('ex.mark.partial')]
    : ['bad', '✗', t('ex.mark.wrong')];
  return h('span', {class: `mark ${cls}`, role: 'img', 'aria-label': label}, sign);
}

export class ExerciseWidget {
  constructor(ex, onResult = () => {}) {
    this.id = ex.exercise_id;
    this.kind = ex.kind;
    this.locked = false;
    this.onResult = onResult;
    this.hints = h('div', {class: 'hints'});
    this.result = h('div', {class: 'result', 'aria-live': 'polite'});
    this.controls = this.buildControls(ex);
    this.actions = h('div', {class: 'buttons'}, this.buildButtons());
    this.el = h('section', {class: `exercise kind-${ex.kind}`, 'aria-label': t('ex.exercise')},
      md(ex.prompt_md), this.controls, this.hints, this.actions, this.result);
  }

  buildControls(ex) {
    const name = `answer-${this.id}`;
    if (ex.kind === 'mc') {
      const type = ex.multiple ? 'checkbox' : 'radio';
      return h('fieldset', {class: 'options'},
        h('legend', {class: ex.multiple ? 'muted small' : 'sr-only'}, ex.multiple ? t('ex.choose_all') : t('ex.choose_one')),
        ex.options.map((o) => h('label', {class: 'option'},
          h('input', {type, name, value: o.id}), md(o.text_md, true))));
    }
    if (ex.kind === 'match') {
      return h('div', {class: 'match'}, ex.lefts.map((left) => {
        const id = `${name}-${left.index}`;
        return h('div', {class: 'match-row'},
          h('label', {for: id}, md(left.left_md, true)),
          h('select', {id, 'data-left': left.index},
            h('option', {value: ''}, '—'),
            ex.rights.map((r) => h('option', {value: r.token}, plain(r.right_md)))));
      }));
    }
    if (ex.kind === 'text') {
      this.input = h('input', {type: 'text', 'aria-label': t('ex.your_answer'), autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false'});
    } else if (ex.kind === 'open') {
      this.input = h('textarea', {rows: 3, 'aria-label': t('ex.your_answer')});
    } else {
      return h('div', {class: 'reveal'});   // recall: filled by revealed()
    }
    this.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        this.submit();
      }
    });
    return this.input;
  }

  buildButtons() {
    const hint = h('button', {type: 'button', class: 'secondary', onclick: () => this.requestHint()}, t('ex.hint'));
    const dontKnow = h('button', {type: 'button', class: 'secondary', onclick: () => this.dontKnow()}, t('ex.dont_know'));
    this.hintButton = hint;
    if (this.kind === 'recall') {
      return [h('button', {type: 'button', onclick: () => this.reveal()}, t('ex.reveal')), hint, dontKnow];
    }
    return [h('button', {type: 'button', onclick: () => this.submit()}, t('ex.submit')), hint, dontKnow];
  }

  focus() {
    const target = this.el.querySelector('input, textarea, select, button');
    target?.focus({preventScroll: true});
  }

  async send(path, body = {}) {
    try {
      return await post(`learner/${path}`, {exercise_id: this.id, ...body});
    } catch (e) {
      if (e.code === 'answered') this.lock();
      showError(e);
      return null;
    }
  }

  response() {
    if (this.kind === 'mc') {
      const selected = [...this.controls.querySelectorAll('input:checked')].map((i) => i.value);
      return selected.length ? {selected} : null;
    }
    if (this.kind === 'match') {
      const matches = {};
      for (const select of this.controls.querySelectorAll('select')) {
        if (!select.value) return null;
        matches[select.dataset.left] = select.value;
      }
      return {matches};
    }
    const text = this.input.value.trim();
    return text ? {text} : null;
  }

  async submit() {
    if (this.locked) return;
    const answer = this.response();
    if (!answer) {
      toast(this.kind === 'match' ? t('ex.match_first') : this.kind === 'mc' ? t('ex.choose_first') : t('ex.type_first'));
      return;
    }
    if (await this.send('answer', answer)) this.lock();
  }

  async requestHint() {
    if (await this.send('hint-request')) this.hintRequested();
  }

  async dontKnow() {
    if (await this.send('dont-know')) this.lock();
  }

  async reveal() {
    const result = await this.send('reveal');
    if (result) this.revealed(result.reference_md);
  }

  async selfGrade(correct) {
    if (await this.send('self-grade', {correct})) this.lock();
  }

  // Once only: the answered event may arrive before the POST response,
  // and buttons added after the first lock (Next) must stay usable.
  lock() {
    if (this.locked) return;
    this.locked = true;
    for (const el of this.el.querySelectorAll('input, textarea, select, button')) el.disabled = true;
  }

  setResult(...nodes) {
    this.result.replaceChildren(...nodes.filter(Boolean));
  }

  // --- updates from transcript events ---------------------------------

  answered(ev, live) {
    this.lock();
    if (ev.awaiting === 'grade') {
      this.setResult(h('p', {class: 'pending'}, t('ex.your_answer_label'), ' ',
        ev.dont_know ? t('ex.dont_know_answer') : md(ev.response_md, true), ' — ', t('ex.waiting')));
      return;
    }
    this.showResponse(ev.response);
    const verdict = ev.correct ? (ev.match === 'typo' ? t('ex.correct_typo') : t('ex.correct')) : t('ex.not_quite');
    const showExpected = ev.expected_md && (!ev.correct || ev.match === 'typo') && !this.referenceShown;
    this.setResult(h('p', {}, mark(ev.correct), ' ', verdict),
      this.kind === 'match' && ev.response_md ? h('div', {}, h('span', {class: 'muted'}, t('ex.yours'), ' '), md(ev.response_md, true)) : null,
      showExpected ? h('div', {class: 'expected'}, h('span', {class: 'muted'}, t('ex.answer'), ' '), md(ev.expected_md, true)) : null);
    this.onResult(this, ev.correct, live);
  }

  // The learner's own answer, so a reload shows what was chosen. Match
  // responses come back as pair indices (tokens are secret), so match
  // shows response_md instead.
  showResponse(response) {
    if (!response) return;
    if (this.kind === 'mc') {
      for (const input of this.controls.querySelectorAll('input')) input.checked = (response.selected || []).includes(input.value);
    } else if (this.input && typeof response.text === 'string') {
      this.input.value = response.text;
    }
  }

  graded(ev) {
    this.lock();
    const verdict = ev.correct ? t('ex.correct') : ev.partial ? t('ex.partly') : t('ex.not_quite');
    this.setResult(h('p', {}, mark(ev.correct, ev.partial), ' ', verdict),
      ev.feedback_md ? md(ev.feedback_md) : null,
      ev.reference_md ? h('div', {class: 'expected'}, h('span', {class: 'muted'}, t('ex.reference'), ' '), md(ev.reference_md)) : null);
  }

  overridden(ev) {
    this.result.append(h('p', {class: 'override'}, t('ex.corrected'), ' ', mark(ev.correct), ' ', ev.reason));
  }

  hinted(ev) {
    this.hints.append(h('div', {class: 'hint'}, h('span', {class: 'muted'}, t('ex.hint_label'), ' '), md(ev.text_md)));
  }

  hintRequested() {
    this.hintButton.disabled = true;
    this.hintButton.textContent = t('ex.hint_requested');
  }

  revealed(referenceMd) {
    if (this.referenceShown) return;
    this.referenceShown = true;
    this.controls.append(h('div', {class: 'expected'}, h('span', {class: 'muted'}, t('ex.reference'), ' '), md(referenceMd)));
    if (this.locked) return;
    const knew = h('button', {type: 'button', onclick: () => this.selfGrade(true)}, t('ex.knew'));
    this.actions.replaceChildren(knew, h('button', {type: 'button', class: 'secondary', onclick: () => this.selfGrade(false)}, t('ex.didnt')));
    knew.focus({preventScroll: true});
  }
}

// A drill: keyed exercises one at a time with a progress indicator,
// instant feedback, then the next; a short summary at the end.
export class Drill {
  constructor(ev, register) {
    this.id = ev.drill_id;
    this.widgets = ev.exercises.map((ex) => register(new ExerciseWidget(ex, (w, correct, live) => this.answered(w, correct, live))));
    this.results = new Map();
    this.index = 0;
    this.dots = this.widgets.map(() => h('span', {class: 'dot'}));
    this.counter = h('span', {class: 'muted'});
    this.stage = h('div', {class: 'stage'});
    this.el = h('section', {class: 'drill', 'aria-label': t('ex.drill')},
      h('header', {class: 'drill-head'}, h('strong', {}, t('ex.drill')), this.counter, h('span', {class: 'dots', 'aria-hidden': 'true'}, this.dots)),
      this.stage);
    this.show(0, false);
  }

  show(index, focus) {
    this.index = index;
    if (index >= this.widgets.length) return this.finish();
    this.counter.textContent = `${index + 1} / ${this.widgets.length}`;
    this.dots.forEach((d, i) => d.classList.toggle('current', i === index));
    this.stage.replaceChildren(this.widgets[index].el);
    if (focus) this.widgets[index].focus();
  }

  answered(widget, correct, live) {
    const i = this.widgets.indexOf(widget);
    this.results.set(i, correct);
    this.dots[i].classList.add(correct ? 'ok' : 'bad');
    if (i !== this.index) return;
    if (!live) return this.show(i + 1, false);
    if (correct) {
      setTimeout(() => this.index === i && this.show(i + 1, true), 900);
      return;
    }
    const next = h('button', {type: 'button', class: 'next', onclick: () => this.show(i + 1, true)},
      i + 1 < this.widgets.length ? t('ex.next') : t('ex.finish'));
    widget.result.append(next);
    next.focus({preventScroll: true});
  }

  finish() {
    const right = [...this.results.values()].filter(Boolean).length;
    this.counter.textContent = t('ex.drill_done', {right, total: this.widgets.length});
    this.dots.forEach((d) => d.classList.remove('current'));
    this.stage.replaceChildren(h('ol', {class: 'drill-summary'}, this.widgets.map((w) => {
      const result = w.result.cloneNode(true);
      result.querySelectorAll('button').forEach((b) => b.remove());
      return h('li', {}, w.el.querySelector('.md').cloneNode(true), result);
    })));
  }
}
