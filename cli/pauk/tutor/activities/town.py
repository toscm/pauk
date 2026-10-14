"""Town scene: walk between places, name objects, talk to NPCs (docs/tutor.md 14.3)."""

from __future__ import annotations

from collections import deque

from pauk.tutor.activities.common import GRADE_OUTCOME, LEARNER, OUTCOMES, check_ref, grade_name, normalize, overall

LEARNER_ACTIONS = ('{"go_to": "<place, person or object>"}, {"inspect": "<object here>"}, {"answer": "<name>"}, '
                   '{"dont_know": true}, {"say": {"npc": "<person here>", "text": "..."}}, {"finish": true}')
TEACHER_ACTIONS = ('{"npc": "<id>", "say": "<line in the NPC\'s language>"}, '
                   '{"grade": {"npc": "<id>", "outcomes": {"<ref>": "good", ...}, "feedback": "..."}}')


def _id(value, where: str) -> str:
    if not isinstance(value, str) or not value or normalize(value).replace(" ", "-") != value:
        raise ValueError(f"{where}: ids are lowercase slugs like 'bakery'")
    return value


class TownActivity:
    """A small town of places joined by streets, with objects and NPCs.

    Spec: {"title": "...", "language": "it", "prompt_md": "..."?, "start": "<place>",
           "places": [{"id", "name", "icon", "at": [col, row]}],
           "streets": [["<place>", "<place>"], ...],
           "objects": [{"id", "place", "icon", "hint", "accepted": ["pane", ...], "item": "it/pane"?}],
           "npcs": [{"id", "name", "place", "icon", "persona", "items": [refs the NPC should use],
                     "greeting"?, "goal": {"task_md", "success", "items": [refs], "max_turns": 8}?}]}
    Rules in code: where the learner is (go_to walks the shortest street path),
    what can be inspected or talked to (only things at the current place),
    whether a typed name is right (normalised, article optional, typo = hard),
    how many turns a conversation may take. The teacher speaks for the NPCs
    and grades each NPC goal like an open exercise.
    Evidence: every first answer to an inspected object (recall), every
    graded goal (produce).
    """

    type = "town"

    def __init__(self, spec: dict):
        self.spec = spec
        self.language = spec.get("language")
        places = spec.get("places") or []
        if not places:
            raise ValueError("a town needs places")
        self.places = {}
        for p in places:
            pid = _id(p.get("id"), "place")
            at = p.get("at")
            if not (isinstance(at, list) and len(at) == 2 and all(isinstance(v, int) and 0 <= v < 12 for v in at)):
                raise ValueError(f"place {pid}: at must be [col, row] with 0-11")
            self.places[pid] = {"id": pid, "name": p.get("name") or pid, "icon": p.get("icon", "🏠"), "at": at}
        self.streets: dict[str, set[str]] = {pid: set() for pid in self.places}
        for street in spec.get("streets") or []:
            if not (isinstance(street, list) and len(street) == 2 and all(s in self.places for s in street)):
                raise ValueError(f"street {street}: two place ids")
            a, b = street
            self.streets[a].add(b)
            self.streets[b].add(a)
        self.objects = {}
        for o in spec.get("objects") or []:
            oid = _id(o.get("id"), "object")
            if o.get("place") not in self.places:
                raise ValueError(f"object {oid}: unknown place '{o.get('place')}'")
            if not o.get("accepted"):
                raise ValueError(f"object {oid}: needs accepted names")
            self.objects[oid] = {"id": oid, "place": o["place"], "icon": o.get("icon", "❓"), "hint": o.get("hint"),
                                 "accepted": list(o["accepted"]),
                                 "item": check_ref(o["item"], f"object {oid}") if o.get("item") else None}
        self.npcs = {}
        for n in spec.get("npcs") or []:
            nid = _id(n.get("id"), "npc")
            if n.get("place") not in self.places:
                raise ValueError(f"npc {nid}: unknown place '{n.get('place')}'")
            goal = n.get("goal")
            if goal is not None:
                if not goal.get("task_md") or not goal.get("success") or not goal.get("items"):
                    raise ValueError(f"npc {nid}: a goal needs task_md, success and items")
                goal = {"task_md": goal["task_md"], "success": goal["success"],
                        "items": [check_ref(r, f"npc {nid} goal") for r in goal["items"]],
                        "max_turns": int(goal.get("max_turns", 8))}
            self.npcs[nid] = {"id": nid, "name": n.get("name") or nid, "place": n["place"], "icon": n.get("icon", "🙂"),
                              "persona": n.get("persona", ""), "language": n.get("language", self.language),
                              "items": [check_ref(r, f"npc {nid} items") for r in n.get("items", [])],
                              "greeting": n.get("greeting"), "goal": goal}
        ids = [*self.places, *self.objects, *self.npcs]
        if len(ids) != len(set(ids)):
            raise ValueError("place, object and npc ids must be distinct")
        self.here = spec.get("start") or next(iter(self.places))
        if self.here not in self.places:
            raise ValueError(f"unknown start place '{self.here}'")
        self.trail = [self.here]
        self.inspecting: str | None = None
        self.named: dict[str, dict] = {}           # object -> {answer, match, outcome}
        self.talk: list[dict] = []                 # {npc, from: learner|npc, text}
        self.goals = {nid: {"status": "open", "turns": 0, "outcomes": None, "feedback": None}
                      for nid, n in self.npcs.items() if n["goal"]}
        self.greeted: set[str] = set()
        self.finished = False
        self.gave_up = False
        self._evidence: list[dict] = []
        self._greet()

    def refs(self) -> list[str]:
        refs = [o["item"] for o in self.objects.values() if o["item"]]
        refs += [r for n in self.npcs.values() if n["goal"] for r in n["goal"]["items"]]
        return list(dict.fromkeys(refs))

    @property
    def done(self) -> bool:
        return self.finished

    def evidence(self) -> list[dict]:
        out, self._evidence = self._evidence, []
        return out

    # --- helpers -----------------------------------------------------------------

    def _find(self, target) -> tuple[str, str]:
        """(kind, id) for a place, object or npc given by id or name."""
        if not isinstance(target, str) or not target.strip():
            raise ValueError("name a place, person or object")
        for kind, table in (("place", self.places), ("npc", self.npcs), ("object", self.objects)):
            if target in table:
                return kind, target
        wanted = normalize(target, True)
        for kind, table in (("place", self.places), ("npc", self.npcs)):
            for key, entry in table.items():
                if normalize(entry["name"], True) == wanted:
                    return kind, key
        for key, entry in self.objects.items():
            if entry["hint"] and normalize(entry["hint"], True) == wanted:
                return "object", key
        raise ValueError(f"nothing called '{target}' in this town")

    def _route(self, goal: str) -> list[str]:
        prev = {self.here: None}
        queue = deque([self.here])
        while queue:
            node = queue.popleft()
            for nxt in sorted(self.streets[node]):
                if nxt not in prev:
                    prev[nxt] = node
                    queue.append(nxt)
        if goal not in prev:
            raise ValueError(f"no street leads to {self.places[goal]['name']}")
        path = [goal]
        while prev[path[-1]] is not None:
            path.append(prev[path[-1]])
        return path[::-1][1:]

    def _greet(self) -> None:
        for nid, npc in self.npcs.items():
            if npc["place"] == self.here and nid not in self.greeted and npc["greeting"]:
                self.greeted.add(nid)
                self.talk.append({"npc": nid, "from": "npc", "text": npc["greeting"]})

    def _here(self, kind: str, key: str) -> None:
        table = self.objects if kind == "object" else self.npcs
        if table[key]["place"] != self.here:
            where = self.places[table[key]["place"]]["name"]
            raise ValueError(f"{key} is at {where}; go there first")

    def _object_name(self, oid: str) -> str:
        return self.objects[oid]["accepted"][0]

    def _label(self, oid: str) -> str:
        o = self.objects[oid]
        return f"{o['icon']} {o['hint'] or oid}"

    # --- actions -----------------------------------------------------------------

    def act(self, action: dict, role: str = LEARNER) -> str:
        if "grade" in action:
            return self._grade_goal(action["grade"], role)
        if self.done:
            raise ValueError("the town visit is over")
        if "npc" in action and "say" in action:
            return self._npc_say(action, role)
        if action.get("finish") or action.get("give_up"):
            self.finished = True
            self.gave_up = bool(action.get("give_up"))
            self.inspecting = None
            return "left the town" if not self.gave_up else "gave up"
        if "go_to" in action:
            kind, key = self._find(action["go_to"])
            place = key if kind == "place" else (self.objects if kind == "object" else self.npcs)[key]["place"]
            if place == self.here:
                return f"already at {self.places[place]['name']}"
            path = self._route(place)
            self.here = place
            self.trail.extend(path)
            self.inspecting = None
            self._greet()
            via = [self.places[p]["name"] for p in path[:-1]]
            return f"walked to {self.places[place]['name']}" + (f" via {', '.join(via)}" if via else "")
        if "inspect" in action:
            kind, key = self._find(action["inspect"])
            if kind == "npc":
                raise ValueError(f"{self.npcs[key]['name']} is a person: use say")
            if kind == "place":
                raise ValueError("inspect an object at your place; use go_to for places")
            self._here(kind, key)
            if key in self.named:
                return f"{self._label(key)}: {self._object_name(key)}"
            self.inspecting = key
            return f"inspecting {self._label(key)}: what is it called?"
        if "answer" in action or action.get("dont_know"):
            if not self.inspecting:
                raise ValueError("inspect an object first")
            oid, self.inspecting = self.inspecting, None
            obj = self.objects[oid]
            answer = None if action.get("dont_know") else str(action.get("answer") or "")
            match = grade_name(answer, obj["accepted"], self.language) if answer else "wrong"
            outcome = GRADE_OUTCOME[match]
            self.named[oid] = {"answer": answer, "match": match, "outcome": outcome}
            if obj["item"]:
                self._evidence.append({"mode": "recall", "items": {obj["item"]: outcome},
                                       "detail": {"object": oid, "answer": answer, "match": match}})
            name = self._object_name(oid)
            if match == "exact":
                return f"✓ {name}"
            if match == "typo":
                return f"≈ almost: {name} (you wrote {answer})"
            return f"✗ it is {name}" + (f" (you wrote {answer})" if answer else "")
        if "say" in action:
            if role != LEARNER:
                raise ValueError('only the learner says things; speak for an NPC with {"npc": id, "say": text}')
            say = action["say"]
            if not isinstance(say, dict) or not str(say.get("text") or "").strip():
                raise ValueError('say: {"npc": "<person here>", "text": "..."}')
            kind, key = self._find(say.get("npc") or "")
            if kind != "npc":
                raise ValueError("say: talk to a person")
            self._here(kind, key)
            goal = self.goals.get(key)
            if goal and goal["status"] == "open":
                if goal["turns"] >= self.npcs[key]["goal"]["max_turns"]:
                    raise ValueError("this conversation has reached its length; the teacher is judging it")
                goal["turns"] += 1
            self.talk.append({"npc": key, "from": "learner", "text": str(say["text"]).strip()})
            return f"to {self.npcs[key]['name']}: {str(say['text']).strip()}"
        raise ValueError(f"actions: {LEARNER_ACTIONS}")

    def _npc_say(self, action: dict, role: str) -> str:
        if role == LEARNER:
            raise ValueError("NPC lines come from the teacher")
        kind, key = self._find(action["npc"])
        if kind != "npc" or not str(action["say"] or "").strip():
            raise ValueError('{"npc": "<id>", "say": "<line>"}')
        self.talk.append({"npc": key, "from": "npc", "text": str(action["say"]).strip()})
        return f"{self.npcs[key]['name']}: {str(action['say']).strip()}"

    def _grade_goal(self, grade, role: str) -> str:
        if role == LEARNER:
            raise ValueError("goals are graded by the teacher")
        if not isinstance(grade, dict) or grade.get("npc") not in self.goals:
            raise ValueError(f"grade: {{\"npc\": one of {', '.join(self.goals) or '(no goals)'}, \"outcomes\": {{...}}}}")
        nid = grade["npc"]
        goal, spec = self.goals[nid], self.npcs[nid]["goal"]
        if goal["status"] == "graded":
            raise ValueError(f"the goal of {nid} is already graded")
        outcomes = grade.get("outcomes")
        if not isinstance(outcomes, dict) or set(outcomes) != set(spec["items"]):
            raise ValueError(f"outcomes must cover exactly the goal items: {', '.join(spec['items'])}")
        if any(o not in OUTCOMES for o in outcomes.values()):
            raise ValueError(f"outcomes are {', '.join(OUTCOMES)}")
        if not any(t["npc"] == nid and t["from"] == "learner" for t in self.talk):
            raise ValueError(f"the learner has not talked to {nid} yet")
        goal.update(status="graded", outcomes=dict(outcomes), feedback=grade.get("feedback"))
        self._evidence.append({"mode": "produce", "items": dict(outcomes),
                               "detail": {"npc": nid, "task_md": spec["task_md"], "feedback": grade.get("feedback"),
                                          "conversation": [t for t in self.talk if t["npc"] == nid]}})
        reached = all(o != "fail" for o in outcomes.values())
        return f"goal with {self.npcs[nid]['name']}: {'reached' if reached else 'not reached'}"

    # --- views -------------------------------------------------------------------

    def _npc_view(self, nid: str, role: str) -> dict:
        n = self.npcs[nid]
        out = {"id": nid, "name": n["name"], "place": n["place"], "icon": n["icon"]}
        if n["goal"]:
            out["goal"] = {"task_md": n["goal"]["task_md"], **self.goals[nid], "max_turns": n["goal"]["max_turns"]}
        if role != LEARNER:
            out.update(persona=n["persona"], language=n["language"], items=n["items"])
            if n["goal"]:
                out["goal"].update(success=n["goal"]["success"], items=n["goal"]["items"])
        return out

    def _object_view(self, oid: str, role: str) -> dict:
        o = self.objects[oid]
        out = {"id": oid, "place": o["place"], "icon": o["icon"], "hint": o["hint"]}
        if oid in self.named:
            out.update(self.named[oid], name=self._object_name(oid))
        if role != LEARNER:
            out.update(accepted=o["accepted"], item=o["item"])
        return out

    def view(self, role: str = "teacher") -> dict:
        return {"title": self.spec.get("title"), "language": self.language,
                "places": list(self.places.values()),
                "streets": sorted(sorted([a, b]) for a, nbrs in self.streets.items() for b in nbrs if a < b),
                **self.state(role)}

    def state(self, role: str = "teacher") -> dict:
        return {"type": self.type, "prompt_md": self.spec.get("prompt_md"), "here": self.here,
                "trail": list(self.trail), "inspecting": self.inspecting,
                "objects": [self._object_view(o, role) for o in self.objects],
                "npcs": [self._npc_view(n, role) for n in self.npcs],
                "talk": list(self.talk), "done": self.done, "gave_up": self.gave_up}

    def describe(self, role: str = "teacher") -> str:
        place = self.places[self.here]
        lines = [f"Town{': ' + self.spec['title'] if self.spec.get('title') else ''} (language: {self.language})."]
        lines.append(f"You are at {place['name']} ({self.here}).")
        objects = [o for o in self.objects.values() if o["place"] == self.here]
        if objects:
            parts = []
            for o in objects:
                text = f"{self._label(o['id'])} [{o['id']}]"
                if o["id"] in self.named:
                    text += f" = {self._object_name(o['id'])} ({self.named[o['id']]['outcome']})"
                elif role != LEARNER:
                    text += f" [key: {' / '.join(o['accepted'])}]"
                parts.append(text)
            lines.append("Objects here: " + "; ".join(parts) + ".")
        for nid, n in self.npcs.items():
            if n["place"] != self.here:
                continue
            text = f"Person here: {n['icon']} {n['name']} [{nid}]"
            if n["goal"]:
                goal = self.goals[nid]
                text += f"; task: {n['goal']['task_md']}"
                if goal["status"] == "graded":
                    text += f" (graded: {', '.join(f'{r} {o}' for r, o in goal['outcomes'].items())})"
                else:
                    text += f" ({goal['turns']}/{n['goal']['max_turns']} turns)"
            lines.append(text + ".")
            if role != LEARNER:
                lines.append(f"Persona: {n['persona']} Speaks {n['language']}; should use {', '.join(n['items']) or '-'}.")
                if n["goal"]:
                    lines.append(f"Success: {n['goal']['success']} Goal items: {', '.join(n['goal']['items'])}.")
            talk = [t for t in self.talk if t["npc"] == nid]
            if talk:
                lines.append("Conversation: " + " / ".join(
                    f"{'Learner' if t['from'] == 'learner' else n['name']}: {t['text']}" for t in talk[-8:]))
        streets = sorted(self.places[p]["name"] for p in self.streets[self.here])
        lines.append("Streets lead to: " + ", ".join(streets) + ".")
        lines.append("Places: " + "; ".join(
            f"{p['name']} [{pid}]" + "".join(f", {n['name']}" for n in self.npcs.values() if n["place"] == pid)
            for pid, p in self.places.items()) + ".")
        if self.inspecting:
            lines.append(f"Inspecting {self._label(self.inspecting)}: name it in the town's language with "
                         f'{{"answer": "..."}} or {{"dont_know": true}}.')
        if self.done:
            named = sum(1 for v in self.named.values() if v["outcome"] != "fail")
            lines.append(f"{'Given up' if self.gave_up else 'Finished'}: {named} of {len(self.objects)} objects named.")
        else:
            lines.append(f"Actions: {LEARNER_ACTIONS}.")
        if role != LEARNER:
            pending = [nid for nid, g in self.goals.items() if g["status"] == "open"
                       and any(t["npc"] == nid and t["from"] == "learner" for t in self.talk)]
            waiting = [nid for nid in self.npcs if (talk := [t for t in self.talk if t["npc"] == nid])
                       and talk[-1]["from"] == "learner"]
            if waiting:
                lines.append(f"Waiting for your NPC line: {', '.join(waiting)}.")
            if pending:
                lines.append(f"Ungraded goals: {', '.join(pending)}.")
            lines.append(f"Teacher actions: {TEACHER_ACTIONS}.")
        return " ".join(lines)

    def result(self) -> dict:
        outcomes = [v["outcome"] for v in self.named.values()]
        outcomes += [o for g in self.goals.values() if g["outcomes"] for o in g["outcomes"].values()]
        return {"outcome": overall(outcomes), "items": {},   # evidence was recorded as it happened
                "detail": {"named": {k: v["outcome"] for k, v in self.named.items()},
                           "goals": {k: g["status"] if not g["outcomes"] else g["outcomes"] for k, g in self.goals.items()},
                           "trail": list(self.trail), "gave_up": self.gave_up}}
