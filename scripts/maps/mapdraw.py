"""Shared drawing code for the pauk Germany maps.

Data source
-----------
German state (admin-1) boundary polygons come from Natural Earth,
10m "Admin 1 - States, Provinces" dataset, fetched as GeoJSON from
the official natural-earth-vector GitHub repository:

  https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson

License: Natural Earth data is in the public domain
(https://www.naturalearthdata.com/about/terms-of-use/), so it may be
used, modified and redistributed without restriction.

The ~40 MB world file is downloaded once and cached under
~/.cache/pauk-maps/; only the 16 features with iso_a2 == "DE" are
used.

Rendering
---------
Pure-Python SVG generation with a simple equirectangular projection
(x = lon * cos(mid_lat), y = -lat, scaled to fit the canvas), plus
optional rasterization to PNG via cairosvg (build-time dependency
only; not needed by the pauk app itself).
"""

from __future__ import annotations

import json
import math
import os
import sys
import urllib.request

NE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_admin_1_states_provinces.geojson"
)
DEFAULT_CACHE = os.path.join(
    os.path.expanduser("~"), ".cache", "pauk-maps",
    "ne_10m_admin_1_states_provinces.geojson",
)

# Canvas geometry ----------------------------------------------------------

WIDTH = 600
HEIGHT = 800
MARGIN = 28

# Colors -------------------------------------------------------------------

COL_BG = "#ffffff"
COL_STATE_FILL = "#e8eef4"
COL_STATE_BORDER = "#6b7c8c"
COL_HIGHLIGHT = "#f5a623"
COL_CITY = "#1f2d3a"
COL_ROUTE = "#d62828"
COL_START = "#2a9d3a"
COL_END = "#d62828"

# The ~20 largest German cities (by population).  Bochum and Wuppertal
# are omitted because they sit between Essen and Dortmund and their
# labels cannot be placed legibly at this map size; Karlsruhe and
# Mannheim (next largest) take their slots.
# Each entry: (label, lat, lon, dx, dy, text-anchor)
CITIES = [
    ("Berlin",       52.520, 13.405,   5,  4, "start"),
    ("Hamburg",      53.551,  9.994,   5,  4, "start"),
    ("München",      48.137, 11.575,   5,  4, "start"),
    ("Köln",         50.938,  6.960,  -5,  4, "end"),
    ("Frankfurt",    50.110,  8.682,   5,  9, "start"),
    ("Stuttgart",    48.776,  9.183,   5,  4, "start"),
    ("Düsseldorf",   51.227,  6.773,  -5,  8, "end"),
    ("Leipzig",      51.340, 12.375,   5,  4, "start"),
    ("Dortmund",     51.514,  7.466,   6,  0, "start"),
    ("Essen",        51.456,  7.011,  -2, -6, "end"),
    ("Bremen",       53.079,  8.801,  -5,  4, "end"),
    ("Dresden",      51.050, 13.738,   3,  9, "start"),
    ("Hannover",     52.375,  9.732,   5,  4, "start"),
    ("Nürnberg",     49.454, 11.077,   5,  4, "start"),
    ("Duisburg",     51.435,  6.762,  -5, -1, "end"),
    ("Bielefeld",    52.021,  8.535,   5, -3, "start"),
    ("Bonn",         50.735,  7.100,  -5,  6, "end"),
    ("Münster",      51.961,  7.626,  -5, -3, "end"),
    ("Karlsruhe",    49.007,  8.404,  -5,  6, "end"),
    ("Mannheim",     49.489,  8.466,  -5,  0, "end"),
]

_UMLAUTS = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
     "Ä": "ae", "Ö": "oe", "Ü": "ue"}
)


def slugify(name: str) -> str:
    """'Baden-Württemberg' -> 'baden-wuerttemberg'."""
    s = name.translate(_UMLAUTS).lower()
    s = "".join(c if c.isalnum() else "-" for c in s)
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")


# Data loading -------------------------------------------------------------

def load_states(cache_path: str = DEFAULT_CACHE) -> dict:
    """Return {slug: {"name": str, "rings": [[(lon, lat), ...], ...]}}.

    Downloads the Natural Earth GeoJSON to *cache_path* if missing.
    Rings include holes; they are drawn with fill-rule evenodd.
    """
    if not os.path.exists(cache_path):
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        print(f"downloading {NE_URL}\n         -> {cache_path}",
              file=sys.stderr)
        tmp = cache_path + ".part"
        urllib.request.urlretrieve(NE_URL, tmp)
        os.replace(tmp, cache_path)

    with open(cache_path, encoding="utf-8") as fh:
        data = json.load(fh)

    states = {}
    for feat in data["features"]:
        props = feat["properties"]
        if props.get("iso_a2") != "DE":
            continue
        geom = feat["geometry"]
        polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                 else [geom["coordinates"]])
        rings = [[(pt[0], pt[1]) for pt in ring]
                 for poly in polys for ring in poly]
        states[slugify(props["name"])] = {
            "name": props["name"],
            "rings": rings,
        }
    if len(states) != 16:
        raise RuntimeError(f"expected 16 German states, got {len(states)}")
    return states


# Projection ---------------------------------------------------------------

class Projection:
    """Equirectangular projection fitted to a lon/lat bounding box."""

    def __init__(self, states: dict,
                 width: int = WIDTH, height: int = HEIGHT,
                 margin: int = MARGIN):
        self.width, self.height = width, height
        lons = [p[0] for st in states.values() for r in st["rings"] for p in r]
        lats = [p[1] for st in states.values() for r in st["rings"] for p in r]
        lat_mid = (min(lats) + max(lats)) / 2
        self.kx = math.cos(math.radians(lat_mid))
        xs = [lon * self.kx for lon in (min(lons), max(lons))]
        ys = [-lat for lat in (min(lats), max(lats))]
        span_x = max(xs) - min(xs)
        span_y = max(ys) - min(ys)
        self.scale = min((width - 2 * margin) / span_x,
                         (height - 2 * margin) / span_y)
        self.ox = (width - span_x * self.scale) / 2 - min(xs) * self.scale
        self.oy = (height - span_y * self.scale) / 2 - min(ys) * self.scale

    def __call__(self, lon: float, lat: float) -> tuple[float, float]:
        return (lon * self.kx * self.scale + self.ox,
                -lat * self.scale + self.oy)


# Geometry helpers ---------------------------------------------------------

def _rdp(points: list, tol: float) -> list:
    """Ramer-Douglas-Peucker simplification (iterative)."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        dmax, imax = -1.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            if norm == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                d = abs(dx * (ay - py) - dy * (ax - px)) / norm
            if d > dmax:
                dmax, imax = d, i
        if dmax > tol:
            keep[imax] = True
            stack.append((a, imax))
            stack.append((imax, b))
    return [p for p, k in zip(points, keep) if k]


def _ring_area(ring: list) -> float:
    area = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        area += x1 * y2 - x2 * y1
    return abs(area) / 2


def _fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def state_path(state: dict, proj: Projection, tol: float = 0.6) -> str:
    """SVG path data for one state (all rings, simplified)."""
    parts = []
    for ring in state["rings"]:
        pts = _rdp([proj(lon, lat) for lon, lat in ring], tol)
        if len(pts) < 3:
            continue
        parts.append(
            "M" + "L".join(f"{_fmt(x)} {_fmt(y)}" for x, y in pts) + "Z")
    return "".join(parts)


# SVG assembly -------------------------------------------------------------

def _text_with_halo(x: float, y: float, text: str, anchor: str,
                    size: int = 11, color: str = COL_CITY) -> str:
    common = (f'x="{_fmt(x)}" y="{_fmt(y)}" text-anchor="{anchor}" '
              f'font-family="DejaVu Sans, Helvetica, Arial, sans-serif" '
              f'font-size="{size}"')
    t = _esc(text)
    return (f'<text {common} fill="none" stroke="#ffffff" stroke-width="3" '
            f'stroke-linejoin="round">{t}</text>'
            f'<text {common} fill="{color}">{t}</text>')


def build_svg(states: dict, highlight: str | None = None,
              route: list | None = None,
              cities: list = CITIES,
              title: str | None = None) -> str:
    """Return the complete SVG document as a string.

    highlight: slug of the state to fill with COL_HIGHLIGHT, or None.
    route:     list of (name, lat, lon) waypoints to draw as a
               polyline with start/end markers, or None.
    """
    proj = Projection(states)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{proj.width}" '
        f'height="{proj.height}" '
        f'viewBox="0 0 {proj.width} {proj.height}">',
        f'<rect width="{proj.width}" height="{proj.height}" '
        f'fill="{COL_BG}"/>',
    ]
    if title:
        out.append(_text_with_halo(proj.width / 2, 22, title,
                                   "middle", size=15))

    # Draw big states first so enclaves (Berlin, Bremen, Hamburg) and
    # small states end up on top of their neighbours.
    def projected_area(st):
        return sum(_ring_area([proj(lon, lat) for lon, lat in r])
                   for r in st["rings"])

    ordered = sorted(states.items(),
                     key=lambda kv: projected_area(kv[1]), reverse=True)
    for slug, st in ordered:
        fill = COL_HIGHLIGHT if slug == highlight else COL_STATE_FILL
        out.append(
            f'<path d="{state_path(st, proj)}" fill="{fill}" '
            f'fill-rule="evenodd" stroke="{COL_STATE_BORDER}" '
            f'stroke-width="1" stroke-linejoin="round"/>')

    if route:
        pts = [proj(lon, lat) for _, lat, lon in route]
        poly = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in pts)
        out.append(
            f'<polyline points="{poly}" fill="none" stroke="{COL_ROUTE}" '
            f'stroke-width="4" stroke-linecap="round" '
            f'stroke-linejoin="round" opacity="0.9"/>')
        for x, y in pts[1:-1]:
            out.append(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="3.5" '
                       f'fill="#ffffff" stroke="{COL_ROUTE}" '
                       f'stroke-width="2"/>')

    for name, lat, lon, dx, dy, anchor in cities:
        x, y = proj(lon, lat)
        out.append(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="2.6" '
                   f'fill="{COL_CITY}"/>')
        out.append(_text_with_halo(x + dx, y + dy + 3, name, anchor))

    if route:
        # Start / end markers on top of everything.
        for (nm, lat, lon), col, lbl in ((route[0], COL_START, "Start"),
                                         (route[-1], COL_END, "Ziel")):
            x, y = proj(lon, lat)
            out.append(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="7" '
                       f'fill="{col}" stroke="#ffffff" stroke-width="2"/>')
            out.append(_text_with_halo(x, y - 12, f"{lbl}: {nm}",
                                       "middle", size=12, color=col))

    out.append("</svg>")
    return "\n".join(out)


def write_svg_png(svg: str, base_path: str) -> tuple[str, str]:
    """Write *base_path*.svg and rasterize it to *base_path*.png.

    Returns (svg_path, png_path).
    """
    svg_path = base_path + ".svg"
    png_path = base_path + ".png"
    with open(svg_path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    try:
        import cairosvg
    except ImportError:
        raise SystemExit(
            "cairosvg is required to rasterize PNGs.\n"
            "Create a scratch venv and run e.g.:\n"
            "  python3 -m venv /tmp/mapsenv && "
            "/tmp/mapsenv/bin/pip install cairosvg\n"
            "then re-run this script with /tmp/mapsenv/bin/python.")
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=png_path,
                     output_width=WIDTH)
    return svg_path, png_path
