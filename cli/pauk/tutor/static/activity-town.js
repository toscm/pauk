// Town scene (docs/tutor.md 14.3): places on a small grid joined by
// streets. Tap a place to walk there; at a place, inspect objects and
// name them, or talk to the people. NPC lines come from the teacher.

import { act, lastAction, pressable, rerender, s } from './activity-kit.js';
import { languageName, local, t } from './i18n.js';
import { md } from './md.js';
import { h } from './ui.js';

const CELL_W = 120;
const CELL_H = 110;
const MARK = {good: '✓', hard: '≈', fail: '✗'};

export class TownCard {
  constructor(ev) {
    this.aid = ev.aid;
    this.view = ev.view;
    this.places = Object.fromEntries(ev.view.places.map((p) => [p.id, p]));
    this.last = '';
    this.el = h('section', {class: 'activity town wide', 'aria-label': t('town.aria')});
    this.render();
  }

  update(ev) {
    const asked = ev.state.inspecting && ev.state.inspecting !== this.view.inspecting;
    this.view = {...this.view, ...ev.state};
    this.last = lastAction(ev);
    this.render();
    // the learner just inspected something: the answer field is next
    if (asked && ev.from === 'learner') this.el.querySelector('.inspect input')?.focus();
  }

  done() {
    this.render();
  }

  busy(on) {
    for (const b of this.el.querySelectorAll('button, input')) b.disabled = on;
  }

  // "Italian" in the UI language
  language() {
    return this.view.language ? languageName(this.view.language) : t('town.local_language');
  }

  render() {
    const v = this.view;
    const here = this.places[v.here];
    const head = h('header', {class: 'activity-head'},
      v.title ? h('h3', {}, v.title) : null,
      v.prompt_md ? md(local(v.prompt_md)) : null,
      h('p', {class: 'small'}, t('town.you_are_at'), ' ', h('strong', {}, `${here.icon} ${here.name}`), v.done ? ` · ${t('town.over')}` : ''),
      this.last ? h('p', {class: 'muted small'}, this.last) : null);
    rerender(this.el, [head, h('div', {class: 'town-layout'}, this.svg(), h('div', {class: 'town-side'},
      v.done ? this.outcome() : this.herePanel())), v.done ? null : this.controls()]);
  }

  at(id) {
    const [col, row] = this.places[id].at;
    return [col * CELL_W + CELL_W / 2, row * CELL_H + CELL_H / 2];
  }

  svg() {
    const v = this.view;
    const cols = Math.max(...v.places.map((p) => p.at[0])) + 1;
    const rows = Math.max(...v.places.map((p) => p.at[1])) + 1;
    const streets = v.streets.map(([a, b]) => {
      const [x1, y1] = this.at(a);
      const [x2, y2] = this.at(b);
      return s('line', {x1, y1, x2, y2, class: 'street'});
    });
    const people = (id) => v.npcs.filter((n) => n.place === id).map((n) => n.icon).join('');
    const places = v.places.map((p) => {
      const [x, y] = this.at(p.id);
      const isHere = p.id === v.here;
      const go = () => act(this.aid, {go_to: p.id}, this);
      const attrs = !v.done && !isHere ? {...pressable(t('town.go_to', {place: p.name}), go), 'data-focus': `place-${p.id}`} : {};
      return s('g', {class: `place${isHere ? ' here' : ''}${v.done ? '' : ' walkable'}`, ...attrs},
        s('title', {}, p.name),
        s('rect', {x: x - 52, y: y - 44, width: 104, height: 88, rx: 12}),
        s('text', {x, y: y - 6, 'text-anchor': 'middle', class: 'icon'}, p.icon),
        s('text', {x, y: y + 30, 'text-anchor': 'middle', class: 'name'}, p.name),
        people(p.id) ? s('text', {x: x + 46, y: y - 26, 'text-anchor': 'end', class: 'npc'}, people(p.id)) : null,
        isHere ? s('text', {x: x - 46, y: y - 24, class: 'me'}, '🧍') : null);
    });
    return s('svg', {class: 'town-map', viewBox: `0 0 ${cols * CELL_W} ${rows * CELL_H}`, role: 'group',
                     'aria-label': t('town.map_aria', {place: this.places[v.here].name})},
      s('g', {}, streets), s('g', {}, places));
  }

  herePanel() {
    const v = this.view;
    const objects = v.objects.filter((o) => o.place === v.here);
    const npcs = v.npcs.filter((n) => n.place === v.here);
    return h('div', {class: 'here'},
      v.inspecting ? this.question() : null,
      objects.length ? h('div', {}, h('h4', {}, t('town.things_here')), h('div', {class: 'buttons things'}, objects.map((o) =>
        h('button', {type: 'button', class: `secondary thing ${o.outcome || ''}`, 'data-focus': `thing-${o.id}`,
                     'aria-label': o.name ? `${local(o.hint)}: ${o.name}` : t('town.inspect', {thing: o.hint}),
                     onclick: () => act(this.aid, {inspect: o.id}, this)},
          h('span', {class: 'thing-icon'}, o.icon), ' ', o.name ? `${o.name} ${MARK[o.outcome] || ''}` : local(o.hint))))) : null,
      npcs.map((n) => this.npc(n)),
      !objects.length && !npcs.length ? h('p', {class: 'muted small'}, t('town.nothing_here')) : null);
  }

  question() {
    const v = this.view;
    const o = v.objects.find((x) => x.id === v.inspecting);
    const input = h('input', {type: 'text', 'data-keep': 'answer', autocomplete: 'off', autocapitalize: 'off',
                              'aria-label': t('town.thing_in', {thing: o.hint, language: this.language()}),
                              placeholder: t('town.in_language', {language: this.language()})});
    const submit = (e) => {
      e.preventDefault();
      if (!input.value.trim()) return;
      act(this.aid, {answer: input.value.trim()}, this).then((ok) => { if (ok) input.value = ''; });
    };
    return h('form', {class: 'inspect', onsubmit: submit},
      h('p', {}, h('span', {class: 'big-icon'}, o.icon), ' ', t('town.question', {thing: o.hint, language: this.language()})),
      h('div', {class: 'row'}, input, h('button', {type: 'submit'}, t('app.answer')),
        h('button', {type: 'button', class: 'secondary', onclick: () => act(this.aid, {dont_know: true}, this)}, t('ex.dont_know'))));
  }

  npc(n) {
    const v = this.view;
    const goal = n.goal;
    const lines = v.talk.filter((line) => line.npc === n.id).map((line) =>
      h('p', {class: `line ${line.from}`}, h('strong', {}, line.from === 'npc' ? n.name.split(',')[0] : t('activity.you')), ': ', line.text));
    const input = h('input', {type: 'text', 'data-keep': `say-${n.id}`, autocomplete: 'off',
                              'aria-label': t('town.say_to', {npc: n.name}), placeholder: t('town.say_something', {language: this.language()})});
    const submit = (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      act(this.aid, {say: {npc: n.id, text}}, this).then((ok) => { if (ok) input.value = ''; });
    };
    const full = goal && goal.status === 'open' && goal.turns >= goal.max_turns;
    const waiting = lines.length && v.talk.filter((line) => line.npc === n.id).at(-1).from === 'learner';
    return h('div', {class: 'npc-card'},
      h('h4', {}, `${n.icon} ${n.name}`),
      goal ? h('div', {class: `task ${goal.status}`}, h('span', {class: 'small muted'}, t('town.task'), ' '), md(local(goal.task_md), true),
        goal.status === 'graded'
          ? h('p', {class: 'small'}, goal.reached ? `✓ ${t('town.goal_done')}` : `✗ ${t('town.goal_not_quite')}`,
              goal.feedback ? [' — ', md(goal.feedback, true)] : null,
              goal.gradings < goal.max_gradings ? h('span', {class: 'muted'}, ` (${t('town.try_again')})`) : null)
          : h('p', {class: 'small muted'}, t('town.turns', {turns: goal.turns, max: goal.max_turns}))) : null,
      h('div', {class: 'talk', 'aria-live': 'polite'}, lines),
      waiting ? h('p', {class: 'small muted pending'}, t('town.answering', {npc: n.name.split(',')[0]})) : null,
      full ? h('p', {class: 'small muted'}, t('town.judging'))
           : h('form', {class: 'row say', onsubmit: submit}, input, h('button', {type: 'submit'}, t('town.say'))));
  }

  controls() {
    return h('div', {class: 'buttons'},
      h('button', {type: 'button', class: 'secondary', onclick: () => {
        if (confirm(t('town.confirm_leave'))) act(this.aid, {finish: true}, this);
      }}, t('town.leave')));
  }

  outcome() {
    const v = this.view;
    const named = v.objects.filter((o) => o.outcome);
    return h('div', {class: 'here'},
      h('p', {}, t('town.named_count', {named: named.filter((o) => o.outcome !== 'fail').length, total: v.objects.length})),
      named.length ? h('p', {class: 'small'}, named.map((o, i) => [i ? ', ' : '', `${o.icon} ${o.name} ${MARK[o.outcome]}`])) : null,
      v.npcs.filter((n) => n.goal).map((n) => h('p', {class: 'small'}, `${n.icon} ${n.name}: `,
        n.goal.reached === null ? t('town.task_not_graded') : n.goal.reached ? `${t('town.task_done')} ✓` : `${t('town.task_not_done')} ✗`)));
  }
}
