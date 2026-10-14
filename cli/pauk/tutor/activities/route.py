"""Autobahn route: drive from a start to a goal city (docs/tutor.md 14.3)."""

from __future__ import annotations

import math

from pauk.route import load_graph
from pauk.tutor.activities.common import check_ref

COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]


class RouteActivity:
    """Drive from a start to a goal city on the autobahn graph.

    Spec: {"graph": "germany-autobahn", "start": "muenchen", "goal": "berlin",
           "items": ["concepts/..."]?, "prompt_md": "..."?}
    Actions: {"drive": "<node id or city name>"}, {"undo": true}, {"give_up": true}.
    Result: good within 10 % of the shortest route, hard within 30 %, fail beyond
    or when given up.
    """

    type = "route"

    def __init__(self, spec: dict):
        self.spec = spec
        self.graph = load_graph(spec.get("graph", "germany-autobahn"))
        for field in ("start", "goal"):
            if spec.get(field) not in self.graph.nodes:
                raise ValueError(f"route spec needs a valid {field} node (e.g. muenchen, berlin)")
        if spec["start"] == spec["goal"]:
            raise ValueError("start and goal must differ")
        self.path = [spec["start"]]
        self.gave_up = False
        self.optimal = self.graph.shortest_km(spec["start"], spec["goal"])
        for ref in spec.get("items") or []:
            check_ref(ref, "route items")

    def refs(self) -> list[str]:
        return list(self.spec.get("items") or [])

    @property
    def node(self) -> str:
        return self.path[-1]

    @property
    def km(self) -> int:
        return self.graph.route_km(self.path) or 0

    @property
    def done(self) -> bool:
        return self.gave_up or self.node == self.spec["goal"]

    def _resolve(self, target: str) -> str:
        if target in self.graph.nodes:
            return target
        for node, data in self.graph.nodes.items():
            if data["name"].lower() == str(target).lower():
                return node
        raise ValueError(f"unknown city '{target}'")

    def _bearing(self, a: str, b: str) -> str:
        na, nb = self.graph.nodes[a], self.graph.nodes[b]
        dx = (nb["lon"] - na["lon"]) * math.cos(math.radians((na["lat"] + nb["lat"]) / 2))
        dy = nb["lat"] - na["lat"]
        angle = (math.degrees(math.atan2(dx, dy)) + 360) % 360
        return COMPASS[int((angle + 22.5) // 45) % 8]

    def act(self, action: dict, role: str = "learner") -> str:
        if self.done:
            raise ValueError("the route is finished")
        if action.get("undo"):
            if len(self.path) < 2:
                raise ValueError("nothing to undo")
            self.path.pop()
            return f"back at {self.graph.name_of(self.node)}"
        if action.get("give_up"):
            self.gave_up = True
            return "gave up"
        if "drive" not in action:
            raise ValueError("actions: {\"drive\": city}, {\"undo\": true}, {\"give_up\": true}")
        target = self._resolve(action["drive"])
        km = self.graph.edge_km(self.node, target)
        if km is None:
            raise ValueError(f"no autobahn from {self.graph.name_of(self.node)} to {self.graph.name_of(target)}")
        edge = next(m for m in self.graph.moves(self.node) if m["to"] == target)
        self.path.append(target)
        return f"{edge['autobahn']} to {self.graph.name_of(target)} ({km} km)"

    def view(self, role: str = "teacher") -> dict:
        return {
            "type": self.type,
            "prompt_md": self.spec.get("prompt_md"),
            "graph": {
                "nodes": {n: {"name": d["name"], "lat": d["lat"], "lon": d["lon"]} for n, d in self.graph.nodes.items()},
                "edges": sorted({(min(a, m["to"]), max(a, m["to"]), m["autobahn"], m["km"])
                                 for a, ms in self.graph.adj.items() for m in ms}),
            },
            "start": self.spec["start"], "goal": self.spec["goal"],
            "path": list(self.path), "km": self.km, "done": self.done, "gave_up": self.gave_up,
            "moves": [] if self.done else [{"to": m["to"], "name": self.graph.name_of(m["to"]),
                                            "autobahn": m["autobahn"], "km": m["km"],
                                            "direction": self._bearing(self.node, m["to"])}
                                           for m in self.graph.moves(self.node)],
            "optimal_km": self.optimal if self.done else None,
        }

    def state(self, role: str = "teacher") -> dict:
        """The small part that changes with every action."""
        view = self.view(role)
        view.pop("graph")
        return view

    def describe(self, role: str = "teacher") -> str:
        g = self.graph
        lines = [f"Route from {g.name_of(self.spec['start'])} to {g.name_of(self.spec['goal'])}.",
                 f"Now at {g.name_of(self.node)}; driven {self.km} km via {' → '.join(g.name_of(n) for n in self.path)}."]
        if self.done:
            lines.append("Finished: " + ("gave up." if self.gave_up else f"{self.km} km, shortest possible {self.optimal} km."))
        else:
            lines.append("Roads: " + "; ".join(f"{m['autobahn']} {self._bearing(self.node, m['to'])} to "
                                              f"{g.name_of(m['to'])} ({m['km']} km)" for m in g.moves(self.node)) + ".")
        return " ".join(lines)

    def result(self) -> dict:
        if self.gave_up:
            outcome = "fail"
        else:
            ratio = self.km / self.optimal if self.optimal else 1.0
            outcome = "good" if ratio <= 1.1 else "hard" if ratio <= 1.3 else "fail"
        return {"outcome": outcome, "detail": {"km": self.km, "optimal_km": self.optimal, "path": self.path,
                                              "gave_up": self.gave_up}}

