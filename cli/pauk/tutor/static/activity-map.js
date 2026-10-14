// Map labelling (docs/tutor.md 14.3): a blank map with numbered
// markers; select a marker, then pick or type its name. Graded by the
// host when the learner checks; the learner's view has no answer key.

import { act, lastAction, pressable, rerender, s } from './activity-kit.js';
import { local, t } from './i18n.js';
import { md } from './md.js';
import { h } from './ui.js';

const MARK = {good: '✓', hard: '≈', fail: '✗'};

export class MapLabelsCard {
  constructor(ev) {
    this.aid = ev.aid;
    this.map = ev.view.map;
    this.view = ev.view;
    this.selected = this.firstOpen();
    this.last = '';
    this.el = h('section', {class: 'activity map-labels wide', 'aria-label': t('map.aria')});
    this.render();
  }

  firstOpen(after = 0) {
    const markers = this.view.markers;
    const open = markers.filter((m) => !m.label);
    return (open.find((m) => m.n > after) || open[0] || markers[0])?.n ?? null;
  }

  marker(n) {
    return this.view.markers.find((m) => m.n === n);
  }

  update(ev) {
    const before = this.marker(this.selected)?.label;
    this.view = {...this.view, ...ev.state};
    this.last = lastAction(ev);
    // after a label lands on the selected marker, move on to the next open one
    if (ev.action?.label && Number(ev.action.label.marker) === this.selected && this.marker(this.selected)?.label !== before
        && this.marker(this.selected)?.label) {
      this.selected = this.firstOpen(this.selected);
    }
    this.render();
  }

  done() {
    this.render();
  }

  busy(on) {
    for (const b of this.el.querySelectorAll('button, input')) b.disabled = on;
  }

  select(n) {
    this.selected = n;
    this.render();
    this.el.querySelector('.label-input')?.focus();
  }

  label(name) {
    if (this.selected === null) return;
    act(this.aid, {label: {marker: this.selected, name}}, this);
  }

  render() {
    const v = this.view;
    const labelled = v.markers.filter((m) => m.label).length;
    const head = h('header', {class: 'activity-head'},
      v.prompt_md ? md(local(v.prompt_md)) : h('p', {}, h('strong', {}, t('map.task', {total: v.markers.length}))),
      h('p', {class: 'small muted'}, v.done
        ? (v.gave_up ? t('map.result_gave_up', {correct: v.correct, total: v.markers.length})
                     : t('map.result_checked', {correct: v.correct, total: v.markers.length}))
        : t('map.progress', {labelled, total: v.markers.length})),
      this.last ? h('p', {class: 'muted small'}, this.last) : null);
    rerender(this.el, [head, h('div', {class: 'map-layout'}, this.svg(), h('div', {class: 'map-side'},
      v.done ? null : this.editor(), this.list(), v.done ? null : this.controls()))]);
  }

  svg() {
    const v = this.view;
    const byRegion = new Map(v.markers.filter((m) => m.region !== null).map((m) => [m.region, m]));
    const regions = this.map.regions.map((r, i) => {
      const m = byRegion.get(i);
      const cls = ['region', m && 'target', m && m.n === this.selected && 'selected', m?.outcome].filter(Boolean).join(' ');
      return s('path', {d: r.path, class: cls, 'fill-rule': 'evenodd',
                        onclick: m && !v.done ? () => this.select(m.n) : null});
    });
    const markers = v.markers.map((m) => {
      const cls = ['marker', m.n === this.selected && !v.done && 'selected', m.label && 'labelled', m.outcome].filter(Boolean).join(' ');
      const text = v.done ? `${MARK[m.outcome] || ''} ${m.name}` : m.label;
      const left = m.x > this.map.width * 0.7;
      return s('g', {class: cls, ...(v.done ? {} : pressable(`${t('map.marker', {n: m.n})}${m.label ? `: ${m.label}` : ''}`, () => this.select(m.n)))},
        s('title', {}, `${m.n}${m.label ? `: ${m.label}` : ''}`),
        s('circle', {cx: m.x, cy: m.y, r: 13}),
        s('text', {x: m.x, y: m.y + 5, 'text-anchor': 'middle', class: 'num'}, String(m.n)),
        text ? s('text', {x: left ? m.x - 17 : m.x + 17, y: m.y + 5, 'text-anchor': left ? 'end' : 'start', class: 'name'}, text) : null);
    });
    return s('svg', {class: 'label-map', viewBox: `0 0 ${this.map.width} ${this.map.height}`, role: 'group',
                     'aria-label': t('map.map_aria', {map: this.map.name, total: v.markers.length})},
      s('g', {}, regions), s('g', {}, markers));
  }

  editor() {
    const v = this.view;
    const m = this.marker(this.selected);
    if (!m) return null;
    const title = h('p', {class: 'editor-title'}, h('strong', {}, t('map.marker', {n: m.n})), m.label ? ` · ${t('map.now', {name: m.label})}` : '');
    if (v.input === 'pick') {
      const used = new Set(v.markers.map((x) => x.label).filter(Boolean));
      return h('div', {class: 'label-editor'}, title, h('div', {class: 'buttons names'},
        v.names.map((name) => h('button', {type: 'button', class: used.has(name) ? 'secondary used' : 'secondary',
                                           'data-focus': `name-${name}`, onclick: () => this.label(name)}, name)),
        m.label ? h('button', {type: 'button', class: 'secondary', onclick: () => this.label('')}, t('map.clear')) : null));
    }
    const input = h('input', {type: 'text', class: 'label-input', 'data-keep': 'label', autocomplete: 'off',
                              'aria-label': t('map.name_of', {n: m.n}), placeholder: t('map.name')});
    const submit = (e) => {
      e.preventDefault();
      const name = input.value.trim();
      if (!name) return;
      input.value = '';
      this.label(name);
    };
    return h('form', {class: 'label-editor', onsubmit: submit}, title,
      h('div', {class: 'row'}, input, h('button', {type: 'submit'}, t('map.set')),
        m.label ? h('button', {type: 'button', class: 'secondary', onclick: () => this.label('')}, t('map.clear')) : null));
  }

  list() {
    const v = this.view;
    return h('ul', {class: 'label-list'}, v.markers.map((m) => {
      const text = v.done
        ? [h('span', {class: `mark ${m.outcome === 'good' ? 'ok' : m.outcome === 'hard' ? 'partial' : 'bad'}`}, MARK[m.outcome]), ' ',
           m.name, m.outcome !== 'good' && m.label ? h('span', {class: 'muted'}, ` (${t('map.yours', {name: m.label})})`) : null]
        : [m.label || h('span', {class: 'muted'}, '—')];
      const n = h('span', {class: 'n'}, `${m.n}.`);
      return h('li', {class: m.n === this.selected && !v.done ? 'selected' : null},
        v.done ? [n, ...text] : h('button', {type: 'button', class: 'link', 'data-focus': `marker-${m.n}`,
                                             onclick: () => this.select(m.n)}, n, ...text));
    }));
  }

  controls() {
    const v = this.view;
    return h('div', {class: 'buttons'},
      h('button', {type: 'button', onclick: () => {
        const open = v.markers.filter((m) => !m.label).length;
        if (!open || confirm(t('map.confirm_check', {open}))) act(this.aid, {finish: true}, this);
      }}, t('map.check')),
      v.can_undo ? h('button', {type: 'button', class: 'secondary', onclick: () => act(this.aid, {undo: true}, this)}, t('activity.undo')) : null,
      h('button', {type: 'button', class: 'secondary', onclick: () => {
        if (confirm(t('map.confirm_give_up'))) act(this.aid, {give_up: true}, this);
      }}, t('activity.give_up')));
  }
}
