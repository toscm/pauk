#!/usr/bin/env python3
"""Export the blank Germany base map for the map labelling activity
(docs/tutor.md 14.3) from the generated SVGs in content/maps/.

Writes content/activities/maps/germany.json:

    {"name": "Germany", "width": 600, "height": 800,
     "projection": {"kx": ..., "scale": ..., "ox": ..., "oy": ...},
     "regions": [{"id": "bayern", "name": "Bayern", "path": "M...",
                  "label": [x, y], "lat": ..., "lon": ...}, ...]}

Regions are ordered by area, largest first (the drawing order of
mapdraw.build_svg), so their order says nothing about their names.
`label` is a point well inside the region (the grid point farthest
from its border), where the activity puts a region's marker.
The projection is fitted to the city dots of germany.svg, so points
given as lat/lon land where mapdraw would draw them:
x = lon * kx * scale + ox, y = -lat * scale + oy.

Pure Python, deterministic; run it after generate_state_maps.py and
copy the output into cli/pauk/data/activities/maps/ (a test checks
that both copies are equal).
"""

from __future__ import annotations

import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mapdraw  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPS = os.path.join(REPO, "content", "maps")
OUT = os.path.join(REPO, "content", "activities", "maps", "germany.json")
HIGHLIGHT = 'fill="' + mapdraw.COL_HIGHLIGHT + '"'


def rings(path: str) -> list[list[tuple[float, float]]]:
    out = []
    for part in path.split("Z"):
        nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", part)]
        if len(nums) >= 6:
            out.append(list(zip(nums[::2], nums[1::2])))
    return out


def inside(x: float, y: float, rs) -> bool:
    hit = False   # even-odd over all rings, as the SVG fill-rule
    for ring in rs:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                hit = not hit
    return hit


def border_distance(x: float, y: float, rs) -> float:
    best = math.inf
    for ring in rs:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            dx, dy = x2 - x1, y2 - y1
            t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy or 1)))
            best = min(best, math.hypot(x - x1 - t * dx, y - y1 - t * dy))
    return best


def label_point(rs) -> tuple[float, float]:
    xs = [x for r in rs for x, _ in r]
    ys = [y for r in rs for _, y in r]
    best, point = -1.0, (sum(xs) / len(xs), sum(ys) / len(ys))
    step = max(1.0, min(max(xs) - min(xs), max(ys) - min(ys)) / 30)
    y = min(ys)
    while y <= max(ys):
        x = min(xs)
        while x <= max(xs):
            if inside(x, y, rs):
                d = border_distance(x, y, rs)
                if d > best:
                    best, point = d, (x, y)
            x += step
        y += step
    return round(point[0], 1), round(point[1], 1)


def area(rs) -> float:
    total = 0.0
    for ring in rs:
        total += abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))) / 2
    return total


def fit_projection() -> dict:
    """Least squares of the city dots in germany.svg against mapdraw.CITIES."""
    svg = open(os.path.join(MAPS, "germany.svg"), encoding="utf-8").read()
    dots = [(float(a), float(b)) for a, b in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', svg)]
    if len(dots) != len(mapdraw.CITIES):
        raise SystemExit(f"expected {len(mapdraw.CITIES)} city dots, found {len(dots)}")

    def line(pairs):   # y = a * x + b
        n = len(pairs)
        mx = sum(p for p, _ in pairs) / n
        my = sum(q for _, q in pairs) / n
        a = sum((p - mx) * (q - my) for p, q in pairs) / sum((p - mx) ** 2 for p, _ in pairs)
        return a, my - a * mx

    ax, ox = line([(lon, x) for (_, lat, lon, *_), (x, _) in zip(mapdraw.CITIES, dots)])
    ay, oy = line([(lat, y) for (_, lat, lon, *_), (_, y) in zip(mapdraw.CITIES, dots)])
    scale = -ay
    return {"kx": round(ax / scale, 6), "scale": round(scale, 4), "ox": round(ox, 3), "oy": round(oy, 3)}


def names() -> dict:
    cards = json.load(open(os.path.join(REPO, "content", "germany-maps.json"), encoding="utf-8"))["cards"]
    out = {}
    for card in cards:
        slug = re.search(r"maps/de-([a-z-]+)\.png", card["question_md"]).group(1)
        out[slug] = next(o["text_md"] for o in card["options"] if o["correct"])
    return out


def main() -> None:
    proj = fit_projection()
    regions = []
    for slug, name in sorted(names().items()):
        svg = open(os.path.join(MAPS, f"de-{slug}.svg"), encoding="utf-8").read()
        path = re.search(r'<path d="([^"]+)" ' + HIGHLIGHT, svg).group(1)
        rs = rings(path)
        x, y = label_point(rs)
        regions.append({"id": slug, "name": name, "path": path, "label": [x, y],
                        "lat": round((proj["oy"] - y) / proj["scale"], 3),
                        "lon": round((x - proj["ox"]) / (proj["kx"] * proj["scale"]), 3),
                        "_area": area(rs)})
    regions.sort(key=lambda r: -r["_area"])
    for r in regions:
        del r["_area"]
    data = {"comment": "Generated by scripts/maps/export_activity_map.py from content/maps/ (Natural Earth, public domain).",
            "name": "Germany", "width": mapdraw.WIDTH, "height": mapdraw.HEIGHT, "projection": proj, "regions": regions}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"wrote {OUT}: {len(regions)} regions, projection {proj}")


if __name__ == "__main__":
    main()
