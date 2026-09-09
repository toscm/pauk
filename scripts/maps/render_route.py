#!/usr/bin/env python3
"""Render an Autobahn route on the Germany base map.

Usage:
    render_route.py GRAPH OUT NODE NODE [NODE ...]

    GRAPH   path to content/autobahn-graph.json
    OUT     output path; ".svg"/".png" extension is stripped and
            both OUT.svg and OUT.png are written
    NODE... node ids forming a path through the graph; every
            consecutive pair must be joined by an edge

On success prints the total km and per-leg breakdown as JSON on
stdout, e.g.:

    {"km": 595, "legs": [{"autobahn": "A9", "from": "muenchen",
                          "to": "ingolstadt", "km": 80}, ...]}

Exits non-zero with a message naming the valid neighbors if two
consecutive nodes are not connected.  Deterministic: same inputs,
same outputs.  Requires cairosvg (see generate_state_maps.py).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mapdraw  # noqa: E402


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(2)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        usage="%(prog)s [--cache PATH] GRAPH OUT NODE NODE [NODE ...]")
    ap.add_argument("graph", help="path to autobahn-graph.json")
    ap.add_argument("out", help="output path (writes OUT.svg and OUT.png)")
    ap.add_argument("nodes", nargs="+", help="node ids along the route")
    ap.add_argument("--cache", default=mapdraw.DEFAULT_CACHE,
                    help="path of the cached Natural Earth GeoJSON")
    args = ap.parse_args()

    with open(args.graph, encoding="utf-8") as fh:
        graph = json.load(fh)
    nodes = graph["nodes"]

    # Undirected adjacency: (a, b) -> (autobahn, km)
    adj: dict[str, dict[str, tuple[str, int]]] = {}
    for e in graph["edges"]:
        adj.setdefault(e["from"], {})[e["to"]] = (e["autobahn"], e["km"])
        adj.setdefault(e["to"], {})[e["from"]] = (e["autobahn"], e["km"])

    for nid in args.nodes:
        if nid not in nodes:
            known = ", ".join(sorted(nodes))
            fail(f"unknown node '{nid}'. Known nodes: {known}")
    if len(args.nodes) < 2:
        fail("a route needs at least two nodes")

    legs = []
    for a, b in zip(args.nodes, args.nodes[1:]):
        if b not in adj.get(a, {}):
            neighbors = ", ".join(
                f"{n} ({adj[a][n][0]})" for n in sorted(adj.get(a, {})))
            fail(f"no autobahn edge between '{a}' and '{b}'. "
                 f"Valid neighbors of '{a}': {neighbors}")
        autobahn, km = adj[a][b]
        legs.append({"autobahn": autobahn, "from": a, "to": b, "km": km})

    route = [(nodes[nid]["name"], nodes[nid]["lat"], nodes[nid]["lon"])
             for nid in args.nodes]
    states = mapdraw.load_states(args.cache)
    svg = mapdraw.build_svg(states, route=route)

    base, ext = os.path.splitext(args.out)
    if ext.lower() not in (".svg", ".png"):
        base = args.out
    out_dir = os.path.dirname(os.path.abspath(base))
    os.makedirs(out_dir, exist_ok=True)
    svg_path, png_path = mapdraw.write_svg_png(svg, base)
    print(f"wrote {svg_path} and {png_path}", file=sys.stderr)

    print(json.dumps({"km": sum(l["km"] for l in legs), "legs": legs},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
