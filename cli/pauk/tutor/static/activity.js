// Activities (docs/tutor.md 14): inline cards driven only through
// POST learner/activity, updated from activity_update / activity_done
// events. One renderer per type (route here, map labelling and the
// town in their own modules); unknown types fall back to the text
// description.

import { act, lastAction, s } from './activity-kit.js';
import { MapLabelsCard } from './activity-map.js';
import { TownCard } from './activity-town.js';
import { local, t } from './i18n.js';
import { md } from './md.js';
import { h } from './ui.js';

const WIDTH = 600;
const MARGIN = 40;
const outcomeText = (outcome) => ({good: t('route.outcome.good'), hard: t('route.outcome.hard'),
                                    fail: t('route.outcome.fail')})[outcome] || outcome;
const direction = (d) => ({north: t('route.dir.north'), 'north-east': t('route.dir.north-east'), east: t('route.dir.east'),
                           'south-east': t('route.dir.south-east'), south: t('route.dir.south'),
                           'south-west': t('route.dir.south-west'), west: t('route.dir.west'),
                           'north-west': t('route.dir.north-west')})[d] || d;

class TextCard {
  constructor(ev) {
    this.aid = ev.aid;
    this.body = h('div', {}, md(ev.text));
    this.el = h('section', {class: 'activity', 'aria-label': t('activity.activity')}, this.body);
  }

  update(ev) {
    this.body.replaceChildren(md(ev.text));
  }

  done(ev) {
    this.el.append(h('p', {class: 'small'}, t('activity.finished', {outcome: ev.outcome})));
  }

  busy() {}
}

// Equirectangular projection with cos(mid-latitude) scaling, as in
// render_route_png (cli/pauk/route.py).
function projection(nodes) {
  const lons = Object.values(nodes).map((n) => n.lon);
  const lats = Object.values(nodes).map((n) => n.lat);
  const kx = Math.cos(((Math.min(...lats) + Math.max(...lats)) / 2) * Math.PI / 180);
  const minX = Math.min(...lons) * kx;
  const maxY = Math.max(...lats);
  const scale = (WIDTH - 2 * MARGIN) / ((Math.max(...lons) - Math.min(...lons)) * kx || 1);
  const height = Math.round((maxY - Math.min(...lats)) * scale + 2 * MARGIN);
  return {height, at: (id) => [MARGIN + (nodes[id].lon * kx - minX) * scale, MARGIN + (maxY - nodes[id].lat) * scale]};
}

class RouteCard {
  constructor(ev) {
    this.aid = ev.aid;
    this.view = ev.view;
    this.graph = ev.view.graph;
    this.proj = projection(this.graph.nodes);
    this.result = null;
    this.last = '';
    this.el = h('section', {class: 'activity route wide', 'aria-label': t('route.aria')});
    this.render();
  }

  name(id) {
    return this.graph.nodes[id]?.name || id;
  }

  update(ev) {
    this.view = {...this.view, ...ev.state};
    this.last = lastAction(ev);
    this.render();
  }

  done(ev) {
    this.result = ev;
    this.render();
  }

  busy(on) {
    for (const b of this.el.querySelectorAll('button')) b.disabled = on;
  }

  render() {
    const v = this.view;
    const here = v.path[v.path.length - 1];
    const head = h('header', {class: 'route-head'},
      v.prompt_md ? md(local(v.prompt_md)) : h('p', {}, h('strong', {}, t('route.task', {from: this.name(v.start), to: this.name(v.goal)}))),
      h('p', {class: 'small'}, t('route.now_in'), ' ', h('strong', {}, this.name(here)),
        ` · ${t('route.driven', {km: v.km})} · ${t('route.goal', {city: this.name(v.goal)})}`),
      v.path.length > 1 ? h('p', {class: 'muted small'}, v.path.map((id) => this.name(id)).join(' → ')) : null,
      this.last ? h('p', {class: 'muted small'}, this.last) : null);
    const controls = v.done ? this.outcome() : h('div', {class: 'buttons moves'},
      v.moves.map((m) => h('button', {type: 'button', onclick: () => act(this.aid, {drive: m.to}, this)},
        `${m.autobahn} ${direction(m.direction)} → ${m.name}, ${m.km} km`)),
      v.path.length > 1 ? h('button', {type: 'button', class: 'secondary', onclick: () => act(this.aid, {undo: true}, this)}, t('activity.undo')) : null,
      h('button', {type: 'button', class: 'secondary', onclick: () => {
        if (confirm(t('route.confirm_give_up'))) act(this.aid, {give_up: true}, this);
      }}, t('activity.give_up')));
    const hadFocus = this.el.contains(document.activeElement);
    this.el.replaceChildren(head, this.map(), controls);
    if (hadFocus) this.el.querySelector('.moves button')?.focus();
  }

  outcome() {
    const v = this.view;
    const r = this.result;
    const optimal = r?.optimal_km ?? v.optimal_km;
    const text = v.gave_up
      ? t('route.gave_up', {km: v.km, optimal})
      : t('route.arrived', {city: this.name(v.goal), km: v.km, optimal}) + (r ? ` — ${outcomeText(r.outcome)}` : '');
    return h('p', {class: `route-result ${r?.outcome || ''}`}, text);
  }

  map() {
    const v = this.view;
    const at = this.proj.at;
    const here = v.path[v.path.length - 1];
    const next = new Set(v.done ? [] : v.moves.map((m) => m.to));
    const labelled = new Set([...v.path, ...next, v.start, v.goal]);
    // Label to the left when another labelled city sits just to the right.
    const crowded = (id) => {
      const [x, y] = at(id);
      return [...labelled].some((o) => {
        const [ox, oy] = at(o);
        return o !== id && ox > x && ox - x < 110 && Math.abs(oy - y) < 22;
      });
    };
    const edges = this.graph.edges.map(([a, b, road, km]) => {
      const [x1, y1] = at(a);
      const [x2, y2] = at(b);
      return s('g', {class: 'edge'}, s('title', {}, `${road} · ${this.name(a)} – ${this.name(b)} · ${km} km`),
        s('line', {x1, y1, x2, y2, class: 'hit'}), s('line', {x1, y1, x2, y2, class: 'road'}));
    });
    const route = s('polyline', {class: 'travelled', points: v.path.map((id) => at(id).join(',')).join(' ')});
    const cities = Object.keys(this.graph.nodes).map((id) => {
      const [x, y] = at(id);
      const near = next.has(id);
      const cls = ['city', near && 'next', v.path.includes(id) && 'visited', id === v.start && 'start', id === v.goal && 'goal',
                   id === here && 'here'].filter(Boolean).join(' ');
      const drive = () => act(this.aid, {drive: id}, this);
      return s('g', near ? {class: cls, role: 'button', tabindex: 0, 'aria-label': t('route.drive_to', {city: this.name(id)}), onclick: drive,
                            onkeydown: (e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), drive())} : {class: cls},
        s('title', {}, this.name(id)),
        near ? s('circle', {cx: x, cy: y, r: 14, class: 'target'}) : null,
        s('circle', {cx: x, cy: y, r: id === here ? 9 : labelled.has(id) ? 5 : 3, class: 'dot'}),
        id === v.start || id === v.goal ? s('circle', {cx: x, cy: y, r: 12, class: 'ring'}) : null,
        labelled.has(id) ? (crowded(id) ? s('text', {x: x - 10, y: y - 8, 'text-anchor': 'end'}, this.name(id))
                                        : s('text', {x: x + 10, y: y - 8}, this.name(id))) : null);
    });
    return s('svg', {class: 'route-map', viewBox: `0 0 ${WIDTH} ${this.proj.height}`, role: 'group',
                     'aria-label': t('route.map_aria', {from: this.name(v.start), to: this.name(v.goal), here: this.name(here)})},
      s('g', {}, edges), route, s('g', {}, cities));
  }
}

const CARDS = {route: RouteCard, map_labels: MapLabelsCard, town: TownCard};

export function activityCard(ev) {
  const Card = CARDS[ev.view?.type];
  return Card ? new Card(ev) : new TextCard(ev);
}
