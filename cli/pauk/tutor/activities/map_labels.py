"""Map labelling: name the numbered markers on a blank map (docs/tutor.md 14.3)."""

from __future__ import annotations

from pauk.route import load_graph
from pauk.tutor.activities.common import (GRADE_OUTCOME, LEARNER, Msg, check_ref, grade_name, load_map,
                                          localized, normalize, overall)

ACTIONS = ('{"label": {"marker": 3, "name": "<place name>"}} (an empty name clears), {"undo": true}, '
           '{"finish": true}, {"give_up": true}')


class MapLabelsActivity:
    """Assign a name to every numbered marker; graded when finished.

    Spec: {"map": "germany", "prompt_md": "..."?, "input": "pick" | "type",
           "places": [{"region": "bayern"} | {"city": "leipzig"} | {"lat": .., "lon": .., "name": ".."},
                      ... each optionally with "name", "accepted": [...], "item": "concepts/..."],
           "distractors": ["Kassel"]?}
    `region` is a region of the base map, `city` a node of the autobahn graph.
    Markers are numbered north to south, so their numbers say nothing about
    the names. With `pick` the learner picks from the listed names (places plus
    distractors), with `type` the names are typed and compared after
    normalisation (case, diacritics, "Nuernberg" = "Nürnberg", one typo per
    8 letters counts as hard); a picked name is right or wrong, never a typo.
    Result: one outcome per place (good, hard on a typo, fail when wrong or
    unlabelled), recorded against the place's item. When the teacher ends
    the map (`end()`), only labelled markers are evidence: an untouched
    marker says nothing about the learner.
    """

    type = "map_labels"

    def __init__(self, spec: dict):
        self.spec = spec
        self.map = load_map(spec.get("map", "germany"))
        self.input = spec.get("input", "pick")
        self.prompt_md = localized(spec.get("prompt_md"), "prompt_md")
        if self.input not in ("pick", "type"):
            raise ValueError('input must be "pick" or "type"')
        places = spec.get("places")
        if not isinstance(places, list) or not 1 <= len(places) <= 40:
            raise ValueError("map_labels spec needs 1-40 places")
        regions = {r["id"]: (i, r) for i, r in enumerate(self.map["regions"])}
        markers = []
        for place in places:
            if not isinstance(place, dict):
                raise ValueError("every place is an object")
            region = None
            if "region" in place:
                if place["region"] not in regions:
                    raise ValueError(f"unknown region '{place['region']}' (known: {', '.join(sorted(regions))})")
                region, data = regions[place["region"]]
                x, y = data["label"]
                lat, lon, name, pid = data["lat"], data["lon"], data["name"], data["id"]
            elif "city" in place:
                graph = load_graph(place.get("graph", "germany-autobahn"))
                if place["city"] not in graph.nodes:
                    raise ValueError(f"unknown city '{place['city']}'")
                node = graph.nodes[place["city"]]
                lat, lon, name, pid = node["lat"], node["lon"], node["name"], place["city"]
                x, y = self._project(lat, lon)
            elif "lat" in place and "lon" in place and place.get("name"):
                lat, lon, name, pid = float(place["lat"]), float(place["lon"]), place["name"], None
                x, y = self._project(lat, lon)
            else:
                raise ValueError('a place needs "region", "city", or "lat", "lon" and "name"')
            name = place.get("name") or name
            item = check_ref(place["item"], f"place {name}") if place.get("item") else None
            markers.append({"id": place.get("id") or pid or normalize(name).replace(" ", "-"), "name": name,
                            "accepted": [name, *place.get("accepted", [])], "item": item,
                            "x": round(x, 1), "y": round(y, 1), "lat": round(lat, 2), "lon": round(lon, 2),
                            "region": region})
        for key in ("name", "item"):
            values = [m[key] for m in markers if m[key]]
            if len(values) != len(set(values)):
                raise ValueError(f"two places share a {key}")
        markers.sort(key=lambda m: (m["y"], m["x"]))
        for n, marker in enumerate(markers, 1):
            marker["n"] = n
        self.markers = {m["n"]: m for m in markers}
        names = {m["name"] for m in markers} | {str(d) for d in spec.get("distractors", [])}
        self.names = sorted(names, key=lambda s: normalize(s, True))
        self.labels: dict[int, str] = {}
        self.history: list[tuple[int, str | None]] = []   # (marker, previous label) for undo
        self.finished = False
        self.gave_up = False
        self.ended = False                                 # ended by the teacher, not by the learner
        self.grades: dict[int, str] = {}                   # marker -> exact | typo | wrong

    def _project(self, lat: float, lon: float) -> tuple[float, float]:
        p = self.map["projection"]
        return lon * p["kx"] * p["scale"] + p["ox"], -lat * p["scale"] + p["oy"]

    def refs(self) -> list[str]:
        return [m["item"] for m in self.markers.values() if m["item"]]

    def secret_refs(self) -> set[str]:
        """Refs whose answer the learner has not seen yet: all until graded."""
        return set() if self.done else set(self.refs())

    @property
    def done(self) -> bool:
        return self.finished

    # --- actions -----------------------------------------------------------------

    def act(self, action: dict, role: str = LEARNER) -> str:
        if self.done:
            raise ValueError("the map is finished")
        if action.get("undo"):
            if not self.history:
                raise ValueError("nothing to undo")
            n, previous = self.history.pop()
            self._set(n, previous)
            if previous:
                return Msg("map.undone", "undone: marker {n} is {name} again", n=n, name=previous)
            return Msg("map.undone_empty", "undone: marker {n} is unlabelled again", n=n)
        if action.get("finish") or action.get("give_up"):
            self.gave_up = bool(action.get("give_up"))
            self._grade()
            correct = sum(g != "wrong" for g in self.grades.values())
            if self.gave_up:
                return Msg("map.gave_up", "gave up: {correct} of {total} correct", correct=correct, total=len(self.markers))
            return Msg("map.finished", "finished: {correct} of {total} correct", correct=correct, total=len(self.markers))
        label = action.get("label")
        if not isinstance(label, dict) or "marker" not in label:
            raise ValueError(f"actions: {ACTIONS}")
        try:
            n = int(label["marker"])
        except (TypeError, ValueError):
            raise ValueError("marker must be a number") from None
        if n not in self.markers:
            raise ValueError(f"no marker {n} (markers 1-{len(self.markers)})")
        name = str(label.get("name") or "").strip() or None
        if name and self.input == "pick":
            match = [c for c in self.names if normalize(c, True) == normalize(name, True)]
            if not match:
                raise ValueError(f"'{name}' is not one of the names: {', '.join(self.names)}")
            name = match[0]
        self.history.append((n, self.labels.get(n)))
        self._set(n, name)
        if name:
            return Msg("map.labelled", "marker {n} = {name}", n=n, name=name)
        return Msg("map.cleared", "marker {n} cleared", n=n)

    def end(self) -> str:
        """Ended by the teacher (activity end): graded like a finish, but
        unlabelled markers give no evidence."""
        if self.done:
            raise ValueError("the map is finished")
        self.ended = True
        self._grade()
        correct = sum(g != "wrong" for g in self.grades.values())
        return Msg("map.ended", "ended by the teacher: {correct} of {labelled} labelled markers correct",
                   correct=correct, labelled=len(self.labels))

    def _set(self, n: int, name: str | None) -> None:
        if name:
            self.labels[n] = name
        else:
            self.labels.pop(n, None)

    def _grade(self) -> None:
        self.finished = True
        language = self.spec.get("language")
        self.grades = {n: self._grade_label(self.labels[n], m, language) if n in self.labels else "wrong"
                       for n, m in self.markers.items()}

    def _grade_label(self, label: str, marker: dict, language: str | None) -> str:
        grade = grade_name(label, marker["accepted"], language)
        if self.input == "pick" and grade == "typo":
            return "wrong"   # a picked name is another place, never a typo
        return grade

    # --- views -------------------------------------------------------------------

    def _marker(self, m: dict, role: str) -> dict:
        out = {"n": m["n"], "x": m["x"], "y": m["y"], "lat": m["lat"], "lon": m["lon"], "region": m["region"],
               "label": self.labels.get(m["n"])}
        if role != LEARNER:
            out.update(id=m["id"], name=m["name"], accepted=m["accepted"], item=m["item"])
        if self.done:
            out.update(name=m["name"], outcome=GRADE_OUTCOME[self.grades[m["n"]]])
        return out

    def view(self, role: str = "teacher") -> dict:
        regions = [{"path": r["path"]} if role == LEARNER else {"id": r["id"], "name": r["name"], "path": r["path"]}
                   for r in self.map["regions"]]
        return {"map": {"name": self.map["name"], "width": self.map["width"], "height": self.map["height"],
                        "regions": regions},
                **self.state(role)}

    def state(self, role: str = "teacher") -> dict:
        correct = sum(g != "wrong" for g in self.grades.values())
        return {"type": self.type, "prompt_md": self.prompt_md, "input": self.input,
                "names": self.names if self.input == "pick" else None,
                "markers": [self._marker(m, role) for m in self.markers.values()],
                "can_undo": bool(self.history) and not self.done,
                "done": self.done, "gave_up": self.gave_up, "ended": self.ended,
                "correct": correct if self.done else None}

    def describe(self, role: str = "teacher") -> str:
        how = "picking each name from the list" if self.input == "pick" else "typing each name"
        lines = [f"Map labelling on a blank map of {self.map['name']}: name {len(self.markers)} numbered markers by {how}."]
        parts = []
        for m in self.markers.values():
            text = f"{m['n']} ({m['lat']:.1f}°N {m['lon']:.1f}°E{', a region' if m['region'] is not None else ''})"
            label = self.labels.get(m["n"])
            text += f": {label}" if label else ": unlabelled"
            if self.done:
                text += f" — {GRADE_OUTCOME[self.grades[m['n']]]}, it is {m['name']}"
            elif role != LEARNER:
                text += f" [key: {m['name']}{', ' + m['item'] if m['item'] else ''}]"
            parts.append(text)
        lines.append("Markers: " + "; ".join(parts) + ".")
        if self.done:
            correct = sum(g != "wrong" for g in self.grades.values())
            how = "Ended by the teacher" if self.ended else "Given up" if self.gave_up else "Finished"
            lines.append(f"{how}: {correct} of {len(self.markers)} correct.")
        else:
            if self.input == "pick":
                lines.append("Names: " + ", ".join(self.names) + ".")
            lines.append(f"Actions: {ACTIONS}.")
        return " ".join(lines)

    def result(self) -> dict:
        outcomes = {n: GRADE_OUTCOME[g] for n, g in self.grades.items() if not self.ended or n in self.labels}
        return {"outcome": overall(list(outcomes.values())),
                "mode": "recognize" if self.input == "pick" else "recall",
                "items": {self.markers[n]["item"]: o for n, o in outcomes.items() if self.markers[n]["item"]},
                "detail": {"correct": sum(o != "fail" for o in outcomes.values()), "total": len(outcomes),
                           "labels": {str(n): self.labels.get(n) for n in self.markers}, "gave_up": self.gave_up,
                           "ended": self.ended}}
