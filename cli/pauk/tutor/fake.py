"""In-memory stand-in for the pauk API, for tests and UI development
(`pauk tutor --fake`). It implements only what the session host uses,
with deliberately simple scoring: it is not the memory model, just
enough behaviour to drive the protocol (mastery moves up on success,
down on failure; keyed exercises are graded by plain comparison).
"""

from __future__ import annotations

import copy
import re
import unicodedata

from pauk.client import ApiError

SETTINGS = {
    "tutor.language": "en", "tutor.immersion": {}, "tutor.item_creation": "propose",
    "tutor.merge": "propose", "tutor.new_items_per_15min": 8, "tutor.model": "sonnet",
    "review.after_session": True, "review.auto_triage": False,
}

SEED = [
    ("it", "farfalla", "word", "farfalla", "butterfly", "italian", 70),
    ("it", "ape", "word", "ape", "bee", "italian", 60),
    ("it", "parlare", "word", "parlare", "to speak", "italian", 95),
    ("it", "present-are", "rule", "present tense of -are verbs", "-o, -i, -a, -iamo, -ate, -ano", "italian", 90),
    ("el", "alpha", "symbol", "α", "alpha", "greek", 80),
    ("el", "beta", "symbol", "β", "beta", "greek", 80),
    ("concepts", "retention-time", "term", "Retention time", "Time an analyte takes to elute from an LC column.", "phd", 80),
    ("concepts", "lasso", "term", "Lasso", "Linear regression with an L1 penalty.", "phd", 75),
]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9α-ω]+", " ", s).strip()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _norm(s)).strip("-")


class FakeApi:
    def __init__(self, seed: bool = True):
        self.items: dict[str, dict] = {}
        self.aliases: dict[str, str] = {}
        self.dirs: dict[str, int] = {}
        self.dir_items: dict[int, set[str]] = {}
        self.interactions: list[dict] = []
        self.reports: list[dict] = []
        self.merges: list[dict] = []
        self.sessions: dict[str, dict] = {}
        self.settings_values = copy.deepcopy(SETTINGS)
        self.version = "0.11.0"
        if seed:
            for space, key, kind, label, gloss, dir_path, priority in SEED:
                self._insert({"space": space, "key": key, "kind": kind, "label_md": label,
                              "gloss_md": gloss, "priority": priority})
                self.dir_items.setdefault(self._ensure_dir(dir_path), set()).add(f"{space}/{key}")

    # --- helpers ----------------------------------------------------------------

    def _ensure_dir(self, path: str) -> int:
        if path not in self.dirs:
            self.dirs[path] = len(self.dirs) + 1
        return self.dirs[path]

    def _insert(self, body: dict) -> dict:
        ref = f"{body['space']}/{body['key']}"
        item = {"id": len(self.items) + 1, "ref": ref, "space": body["space"], "key": body["key"],
                "kind": body["kind"], "label_md": body["label_md"], "gloss_md": body.get("gloss_md", ""),
                "body_md": body.get("body_md", ""), "attrs": body.get("attrs", {}),
                "priority": body.get("priority", 50), "level": body.get("level"), "archived": False,
                "merged_into": None, "state": None, "aliases": [], "dirs": [], "links": [], "cards": [],
                "interactions": []}
        self.items[ref] = item
        return item

    def _resolve(self, ref) -> dict:
        ref = str(ref)
        ref = self.aliases.get(ref, ref)
        if ref.isdigit():
            for item in self.items.values():
                if item["id"] == int(ref):
                    return item
        if ref not in self.items:
            raise ApiError(404, "not_found", f"Item {ref} not found")
        return self.items[ref]

    # --- API surface used by the session host ------------------------------------

    def health(self) -> dict:
        return {"status": "ok", "db": "ok", "version": self.version}

    def settings(self) -> dict:
        return copy.deepcopy(self.settings_values)

    def update_settings(self, changes: dict) -> dict:
        for name in changes:
            if name not in self.settings_values:
                raise ApiError(400, "validation", f"Unknown setting '{name}'")
        self.settings_values.update(changes)
        return self.settings()

    def get_item(self, ref) -> dict:
        return copy.deepcopy(self._resolve(ref))

    def list_items(self, q=None, dir=None, recursive=None, space=None, kind=None, limit=50, **_) -> list[dict]:
        out = []
        for item in self.items.values():
            if item["archived"]:
                continue
            if space and item["space"] != space:
                continue
            if kind and item["kind"] != kind:
                continue
            if dir and item["ref"] not in self.dir_items.get(dir, set()):
                continue
            if q and _norm(q) not in _norm(item["label_md"] + " " + item["gloss_md"] + " " + item["key"]):
                continue
            out.append(copy.deepcopy(item))
        return out[:limit]

    def resolve_dir(self, path: str) -> dict:
        if path not in self.dirs:
            raise ApiError(404, "not_found", f"No directory {path}")
        return {"id": self.dirs[path], "name": path.split("/")[-1]}

    def quiz_dirs(self) -> list[dict]:
        return [{"id": i, "path": p, "name": p.split("/")[-1], "cards_total": 0, "runs": 0, "performance": None}
                for p, i in sorted(self.dirs.items())]

    def create_dir(self, name: str, parent_id=None) -> dict:
        parent = next((p for p, i in self.dirs.items() if i == parent_id), None) if parent_id else None
        path = f"{parent}/{name}" if parent else name
        return {"id": self._ensure_dir(path), "name": name}

    def profile_dirs(self, dir_id: int) -> list[dict]:
        root = next(p for p, i in self.dirs.items() if i == dir_id)
        out = []
        for path, i in sorted(self.dirs.items()):
            if path == root or path.startswith(root + "/"):
                refs = set().union(*(v for p, d in self.dirs.items() if p == path or p.startswith(path + "/")
                                     for v in [self.dir_items.get(d, set())]))
                summary = self._summary([self.items[r] for r in refs if r in self.items])
                out.append({"id": i, "path": path[len(root) + 1:], **summary})
        return out

    def _summary(self, items: list[dict]) -> dict:
        by = {str(i): 0 for i in range(6)}
        for item in items:
            by[str((item["state"] or {}).get("mastery", 0))] += 1
        return {"items": len(items), "by_mastery": by, "due": 0}

    def link_item_dir(self, dir_id: int, ref) -> None:
        self.dir_items.setdefault(dir_id, set()).add(self._resolve(ref)["ref"])

    def profile(self, dir_id=None, space=None) -> dict:
        items = self.list_items(dir=dir_id, space=space, limit=10_000)
        by = {str(i): 0 for i in range(6)}
        for item in items:
            by[str((item["state"] or {}).get("mastery", 0))] += 1
        return {"items": len(items), "by_mastery": by, "coverage": None, "due": 0, "most_lapses": []}

    def next_items(self, dir_id=None, space=None, n=10, new=None) -> dict:
        items = self.list_items(dir=dir_id, space=space, limit=10_000)
        def entry(i, reason):
            return {k: i[k] for k in ("ref", "kind", "label_md", "gloss_md", "priority", "level", "state")} | {"reason": reason}
        review = [entry(i, "due: fake") for i in items if i["state"] and i["state"]["mastery"] < 3]
        fresh = sorted((i for i in items if not i["state"]), key=lambda i: -i["priority"])
        limit = n if new is None else min(n, new)
        return {"review": review[:n], "new": [entry(i, f"new: priority {i['priority']}") for i in fresh][:limit]}

    def record_interaction(self, body: dict) -> dict:
        for existing in self.interactions:
            if existing["uuid"] == body.get("uuid"):
                return {**existing["result"], "created": False}
        match = None
        outcomes = {e["ref"]: e.get("outcome") for e in body["items"]}
        if body["mode"] != "introduce" and any(o is None for o in outcomes.values()):
            match = self._grade(body["exercise"], body["response"])
            outcome = {"exact": "good", "typo": "hard", "wrong": "fail"}[match]
            outcomes = {r: o or outcome for r, o in outcomes.items()}
        items = []
        for ref, outcome in outcomes.items():
            item = self._resolve(ref)
            before = (item["state"] or {}).get("mastery", 0)
            state = item["state"] or {"mastery": 0, "recall": 1.0, "reps": 0, "lapses": 0,
                                      "status": "active", "note": "", "best_mode": None}
            if body["mode"] == "introduce":
                state["mastery"] = max(state["mastery"], 1)
            elif outcome == "fail":
                state["mastery"] = max(1, state["mastery"] - 1)
                state["lapses"] += 1
                state["reps"] += 1
            else:
                state["mastery"] = min(5, max(2, state["mastery"] + 1))
                state["reps"] += 1
            item["state"] = state
            items.append({"ref": item["ref"], "outcome": outcome, "mastery_before": before, "state": copy.deepcopy(state)})
        result = {"uuid": body["uuid"], "created": True, "match": match, "items": items}
        if match is not None:
            result["correct"] = match != "wrong"
            result["expected"] = {}
        self.interactions.append({**body, "result": result, "amendments": []})
        return result

    def amend_interaction(self, uuid: str, body: dict) -> dict:
        for interaction in self.interactions:
            if interaction["uuid"] == uuid:
                interaction["amendments"].append(body)
                items = []
                for e in body["items"]:
                    item = self._resolve(e["ref"])
                    before = (item["state"] or {}).get("mastery", 0)
                    if e["outcome"] != "fail" and item["state"]:
                        item["state"]["mastery"] = min(5, item["state"]["mastery"] + 1)
                    items.append({"ref": item["ref"], "outcome": e["outcome"], "mastery_before": before,
                                  "state": copy.deepcopy(item["state"])})
                return {"uuid": uuid, "created": False, "match": interaction["result"].get("match"), "items": items}
        raise ApiError(404, "not_found", "no such interaction")

    def create_item(self, body: dict) -> dict:
        body = dict(body)
        dry = body.pop("dry_run", False)
        space = body.get("space")
        if not space or not body.get("kind") or not body.get("label_md"):
            raise ApiError(400, "validation", "space, kind and label_md are required")
        key = body.get("key") or _slug(body["label_md"])
        ref = f"{space}/{key}"
        if ref in self.items or ref in self.aliases:
            return {"created": False, "via": "key", "item": self.get_item(ref)}
        if body.get("same_as"):
            target = self._resolve(body["same_as"])
            if not dry:
                self.aliases[ref] = target["ref"]
            return {"created": False, "via": "same_as", "item": copy.deepcopy(target)}
        norm = _norm(body["label_md"])
        candidates = [{"ref": i["ref"], "kind": i["kind"], "label_md": i["label_md"], "gloss_md": i["gloss_md"], "reason": "label"}
                      for i in self.items.values()
                      if i["space"] == space and (norm in _norm(i["label_md"]) or _norm(i["label_md"]) in norm)
                      and i["ref"] not in body.get("distinct_from", [])]
        if candidates:
            raise ApiError(409, "possible_duplicates", "Similar items exist", {"candidates": candidates})
        if body.get("distinct_from") and not body.get("reason"):
            raise ApiError(400, "validation", "distinct_from needs a reason")
        preview = {"ref": ref, "space": space, "key": key, "kind": body["kind"], "label_md": body["label_md"],
                   "gloss_md": body.get("gloss_md", "")}
        if dry:
            return {"created": False, "would_create": True, "item": preview}
        item = self._insert({**body, "key": key})
        return {"created": True, "item": copy.deepcopy(item)}

    def set_item_flags(self, ref, status=None, note=None) -> dict:
        item = self._resolve(ref)
        state = item["state"] or {"mastery": 0, "recall": None, "reps": 0, "lapses": 0,
                                  "status": "active", "note": "", "best_mode": None}
        if status:
            state["status"] = status
        if note is not None:
            state["note"] = note
        item["state"] = state
        return copy.deepcopy(item)

    def merge_items(self, into, body: dict) -> dict:
        a, b = self._resolve(into), self._resolve(body["from"])
        b["archived"] = True
        b["merged_into"] = a["ref"]
        self.aliases[b["ref"]] = a["ref"]
        merge = {"id": len(self.merges) + 1, "into": a["ref"], "from": b["ref"], "status": "done",
                 "reason": body["reason"], "suggested_by": body.get("by", "human")}
        self.merges.append(merge)
        return merge

    def suggest_merge(self, body: dict) -> dict:
        merge = {"id": len(self.merges) + 1, "into": self._resolve(body["into"])["ref"],
                 "from": self._resolve(body["from"])["ref"], "status": "suggested",
                 "reason": body["reason"], "suggested_by": body.get("by", "human")}
        self.merges.append(merge)
        return merge

    def list_merges(self, status=None) -> list[dict]:
        return [m for m in self.merges if status is None or m["status"] == status]

    def decide_merge(self, merge_id: int, action: str) -> dict:
        merge = self.merges[merge_id - 1]
        if action == "accept":
            self.merge_items(merge["into"], {"from": merge["from"], "reason": merge["reason"]})
            self.merges.pop()
            merge["status"] = "done"
        else:
            merge["status"] = "dismissed"
        return merge

    def create_report(self, body: dict) -> dict:
        report = {"id": len(self.reports) + 1, "status": "new", **body}
        self.reports.append(report)
        return report

    def start_tutor_session(self, body: dict) -> dict:
        self.sessions.setdefault(body["uid"], dict(body))
        return self.sessions[body["uid"]]

    def update_tutor_session(self, uid: str, body: dict) -> dict:
        self.sessions.setdefault(uid, {"uid": uid}).update(body)
        return self.sessions[uid]

    # --- grading --------------------------------------------------------------------

    @staticmethod
    def _grade(exercise: dict, response: dict) -> str:
        kind = exercise["kind"]
        if kind == "mc":
            return "exact" if sorted(map(str, response.get("selected", []))) == sorted(map(str, exercise["correct"])) else "wrong"
        if kind == "match":
            matches = response.get("matches", {})
            return "exact" if all(int(matches.get(str(i), -1)) == i for i in range(len(exercise["pairs"]))) else "wrong"
        answer = _norm(response.get("text", ""))
        accepted = [_norm(a) for a in exercise["accepted"]]
        return "exact" if answer in accepted else "wrong"
