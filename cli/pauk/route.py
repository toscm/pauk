"""Deterministic route navigation over a bundled graph.

A route task is played by picking edges (multiple choice), never by
free typing, and the kilometres are summed here from the graph —
never trusted to an LLM. The same module renders the chosen route
onto a schematic map (Pillow only, so it works wherever the CLI
runs).
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from importlib import resources


@lru_cache(maxsize=8)
def load_graph(name: str) -> "Graph":
    with resources.files("pauk.data").joinpath(f"{name}.json").open("rb") as fh:
        return Graph(json.load(fh))


class Graph:
    def __init__(self, data: dict):
        self.nodes: dict[str, dict] = data["nodes"]
        # adjacency: node -> list of (neighbor, autobahn, km); edges
        # are undirected
        self.adj: dict[str, list[dict]] = {n: [] for n in self.nodes}
        for e in data["edges"]:
            self.adj[e["from"]].append(
                {"to": e["to"], "autobahn": e["autobahn"], "km": e["km"]}
            )
            self.adj[e["to"]].append(
                {"to": e["from"], "autobahn": e["autobahn"], "km": e["km"]}
            )

    def name_of(self, node: str) -> str:
        return self.nodes.get(node, {}).get("name", node)

    def moves(self, node: str) -> list[dict]:
        """Available edges from a node, sorted by autobahn then name."""
        return sorted(
            self.adj.get(node, []),
            key=lambda m: (m["autobahn"], self.name_of(m["to"])),
        )

    def edge_km(self, a: str, b: str) -> int | None:
        for m in self.adj.get(a, []):
            if m["to"] == b:
                return m["km"]
        return None

    def route_km(self, path: list[str]) -> int | None:
        """Total km of a node path, or None if any hop is not an edge."""
        total = 0
        for a, b in zip(path, path[1:]):
            km = self.edge_km(a, b)
            if km is None:
                return None
            total += km
        return total

    def shortest_km(self, start: str, goal: str) -> int | None:
        """Dijkstra — the optimum, for showing the user the target."""
        import heapq

        dist = {start: 0}
        pq = [(0, start)]
        while pq:
            d, node = heapq.heappop(pq)
            if node == goal:
                return d
            if d > dist.get(node, math.inf):
                continue
            for m in self.adj.get(node, []):
                nd = d + m["km"]
                if nd < dist.get(m["to"], math.inf):
                    dist[m["to"]] = nd
                    heapq.heappush(pq, (nd, m["to"]))
        return dist.get(goal)


def render_route_png(graph: Graph, path: list[str], width: int = 520, height: int = 640) -> bytes:
    """A schematic map: all cities as faint dots, the travelled route
    highlighted, start/goal marked. Uses the graph's own lon/lat box
    (no external map data needed)."""
    from PIL import Image, ImageDraw

    lons = [v["lon"] for v in graph.nodes.values()]
    lats = [v["lat"] for v in graph.nodes.values()]
    lat_mid = (min(lats) + max(lats)) / 2
    kx = math.cos(math.radians(lat_mid))
    margin = 40

    xs = [lon * kx for lon in (min(lons), max(lons))]
    ys = [-lat for lat in (min(lats), max(lats))]
    span_x = max(xs) - min(xs) or 1
    span_y = max(ys) - min(ys) or 1
    scale = min((width - 2 * margin) / span_x, (height - 2 * margin) / span_y)
    ox = (width - span_x * scale) / 2 - min(xs) * scale
    oy = (height - span_y * scale) / 2 - min(ys) * scale

    def px(node: str) -> tuple[float, float]:
        v = graph.nodes[node]
        return (v["lon"] * kx * scale + ox, -v["lat"] * scale + oy)

    img = Image.new("RGB", (width, height), (245, 245, 245))
    d = ImageDraw.Draw(img)
    # faint full network
    drawn = set()
    for a, neighbors in graph.adj.items():
        for m in neighbors:
            key = tuple(sorted((a, m["to"])))
            if key in drawn:
                continue
            drawn.add(key)
            d.line([px(a), px(m["to"])], fill=(210, 210, 210), width=1)
    for node in graph.nodes:
        x, y = px(node)
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(180, 180, 180))
    # the travelled route
    if len(path) > 1:
        d.line([px(n) for n in path], fill=(200, 30, 30), width=3)
    for node in path:
        x, y = px(node)
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(200, 30, 30))
        d.text((x + 5, y - 6), graph.name_of(node), fill=(30, 30, 30))
    if path:
        for node, color in ((path[0], (20, 120, 40)), (path[-1], (30, 60, 200))):
            x, y = px(node)
            d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=color, width=2)

    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
