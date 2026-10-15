"""One tutoring session: transcript, exercises, rules (docs/tutor.md 8–10).

The session is plain Python, independent of HTTP, so its rules are
testable without a server: the host (host.py) only maps routes to
the methods here. Everything persistent goes through `api` (the pauk
Client, or FakeApi in tests and UI development); the session never
computes scores.

Event visibility: every event carries the full data for teacher and
observer; `learner` is the learner's view of it (None = not shown to
the learner), `teacher` an optional compact view for the teacher (the
observer keeps the full data, e.g. activity states for rendering).
Audit events (every teacher command, reads included) and annotations
are observer-only.
"""

from __future__ import annotations

import json
import random
import secrets
import threading
import time
import uuid as uuidlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from pauk.client import ApiError
from pauk.tutor import activities
from pauk.tutor import protocol as p
from pauk.tutor.activities.common import Msg

SAME = object()   # learner view equals the full data
TEACHER = "teacher"
LEARNER = "learner"
OBSERVER = "observer"
SYSTEM = "system"


class SessionError(Exception):
    def __init__(self, status: int, code: str, message: str, data: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.data = data or {}


@dataclass
class Event:
    seq: int
    at: float
    frm: str
    type: str
    data: dict
    learner: Optional[dict]
    observer_only: bool = False
    teacher: Optional[dict] = None

    def envelope(self) -> dict:
        return {"seq": self.seq, "at": self.at, "from": self.frm, "type": self.type}

    def full(self) -> dict:
        # the envelope wins over payload fields of the same name
        return {**self.data, **self.envelope()}

    def for_learner(self) -> Optional[dict]:
        if self.learner is None or self.observer_only:
            return None
        return {**self.learner, **self.envelope()}

    def for_teacher(self) -> dict:
        return self.full() if self.teacher is None else {**self.teacher, **self.envelope()}


@dataclass
class ExerciseState:
    id: str
    ex: p.Exercise
    drill_id: Optional[str] = None
    status: str = "open"          # open | answered | graded
    hinted: bool = False
    uuid: Optional[str] = None    # interaction uuid once recorded
    response: Optional[dict] = None
    dont_know: bool = False
    overridden: bool = False
    revealed: bool = False
    right_tokens: dict[str, int] = field(default_factory=dict)   # match: token -> pair index
    result: Optional[dict] = None


def _summary_msg(summary: str) -> dict:
    """The message id and parameters of an activity summary, so the
    browser shows it in the learner's UI language (English text stays in
    `summary` for agents)."""
    return {"summary_msg": summary.message()} if isinstance(summary, Msg) else {}


def _now() -> float:
    return round(time.time(), 3)


def locked(method):
    """Serialize state changes: routes run in a thread pool, and two
    parallel answers must not both pass the `status == "open"` check."""
    def wrapper(self, *args, **kwargs):
        with self.cond:
            return method(self, *args, **kwargs)
    wrapper.__name__ = method.__name__
    wrapper.__doc__ = method.__doc__
    return wrapper


class Session:
    def __init__(self, api, sid: str | None = None, store_dir: Path | None = None,
                 clock: Callable[[], float] = _now, rng: random.Random | None = None, simulation: bool = False):
        self.api = api
        # simulated sessions mark their evidence, so it can be told apart
        self.source = "simulation" if simulation else "tutor"
        self.sid = sid or "s-" + secrets.token_hex(4)
        self.keys = {LEARNER: secrets.token_urlsafe(16), TEACHER: secrets.token_urlsafe(16),
                     OBSERVER: secrets.token_urlsafe(16)}
        self.clock = clock
        self.rng = rng or random.Random()
        self.started_at = clock()
        self.events: list[Event] = []
        self.cond = threading.Condition()
        self.exercises: dict[str, ExerciseState] = {}
        self.drills: dict[str, list[str]] = {}
        self.proposals: dict[str, dict] = {}
        self.activities: dict[str, Any] = {}
        self.activity_writes: list[dict] = []        # activity evidence waiting to be recorded (retried)
        self.activity_final: set[str] = set()        # aids whose final result is queued
        self.activity_done_sent: set[str] = set()    # aids whose activity_done was emitted
        self.activity_closed: set[str] = set()       # aids the teacher ended explicitly
        self._missing_items: set[str] = set()        # refs that answered 404 (until an item is added)
        self.teacher_seen_seq = 0                    # every event up to here reached the teacher (state)
        self.teacher_delivered: set[int] = set()     # learner events delivered by wait after that
        self.goal: Optional[dict] = None
        self.goal_started: Optional[float] = None
        self.ended = False
        self.time_warned = False
        self.last_learner_activity = clock()
        self.learner_ended_at: Optional[float] = None
        self.teacher_attached = False
        self.teacher_agent: Optional[str] = None
        self.teacher_model: Optional[str] = None     # reported by a managed agent (agent.py)
        self.teacher_last_seen: Optional[float] = None
        self.agent_running = False
        self.touched: dict[str, dict] = {}       # ref -> {label_md, before, now}
        self.new_refs: set[str] = set()
        self._item_cache: dict[str, dict] = {}
        self._counter = 0
        self.settings = self._safe(api.settings, default={})
        self.api_version = self._version(self._safe(api.health, default={}).get("version", "0"))
        self.store = None
        if store_dir is not None:
            store_dir.mkdir(parents=True, exist_ok=True)
            self.store = store_dir / f"{self.sid}.jsonl"
        self._safe(lambda: api.start_tutor_session({"uid": self.sid}), default=None)

    # --- events ------------------------------------------------------------

    def emit(self, frm: str, type_: str, data: dict, learner: Any = SAME, observer_only: bool = False,
             teacher: Optional[dict] = None) -> Event:
        with self.cond:
            event = Event(len(self.events) + 1, self.clock(), frm, type_, data,
                          data if learner is SAME else learner, observer_only, teacher)
            self.events.append(event)
            self.cond.notify_all()
        if self.store is not None:
            with self.store.open("a", encoding="utf-8") as f:
                f.write(json.dumps({**event.full(), "learner_view": event.for_learner() is not None,
                                    "observer_only": observer_only}, ensure_ascii=False) + "\n")
        return event

    def audit(self, command: str, args: dict | None = None) -> None:
        self.teacher_last_seen = self.clock()
        self.emit(SYSTEM, "audit", {"command": command, "args": args or {}}, learner=None, observer_only=True)

    def events_for(self, role: str, after: int = 0) -> list[dict]:
        with self.cond:
            events = self.events[after:]
        if role == LEARNER:
            return [e for e in (ev.for_learner() for ev in events) if e is not None]
        if role == TEACHER:
            return [e.for_teacher() for e in events if not e.observer_only]
        return [e.full() for e in events]

    def teacher_sync(self) -> dict:
        """Learner events the teacher has not received through wait or
        state yet, added to every teacher action response."""
        with self.cond:
            unseen = [e for e in self.events[self.teacher_seen_seq:]
                      if e.frm == LEARNER and not e.observer_only and e.seq not in self.teacher_delivered]
        out: dict = {"unseen": len(unseen)}
        ended = [e.seq for e in unseen if e.type == "end"]
        if ended:
            out["warning"] = f"the learner ended the session at seq {ended[0]}: wrap up and run `pauk teach end`"
        elif unseen:
            out["hint"] = f"{len(unseen)} learner event(s) not seen yet: run `pauk teach wait --after {unseen[0].seq - 1}`"
        return out

    def wait(self, role: str, after: int, timeout: float) -> dict:
        """Block until events for `role` after `after` exist (max timeout)."""
        if role == TEACHER:
            self.teacher_last_seen = self.clock()
        deadline = time.monotonic() + timeout
        with self.cond:
            while True:
                events = self.events_for(role, after)
                last_seq = len(self.events)   # same snapshot as the events
                if events or self.ended:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.cond.wait(min(remaining, 1.0))
            if role == TEACHER:
                self.teacher_delivered.update(e["seq"] for e in events if e["from"] == LEARNER)
        return {"events": events, "last_seq": last_seq, "ended": self.ended}

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}{self._counter}"

    # --- shared state views --------------------------------------------------

    def status(self, role: str | None = None) -> dict:
        connected = self.teacher_last_seen is not None and self.clock() - self.teacher_last_seen < 150
        return {
            "sid": self.sid,
            "goal": self.goal,
            "ended": self.ended,
            "elapsed_s": round(self.clock() - (self.goal_started or self.started_at)),
            "goal_started_at": self.goal_started,
            "now": self.clock(),
            "teacher_connected": connected,
            "teacher_agent": self.teacher_agent,
            "teacher_model": self.teacher_model,
            "agent_running": self.agent_running,
            "touched": self._touched(role),
            "stats": self.stats(),
            "settings": self.settings,
        }

    def stats(self) -> dict:
        """Exact counts for summaries: graded exercises, correct ones, typos, unanswered."""
        graded = [s for s in self.exercises.values() if s.status == "graded"]
        correct = [s for s in graded if (s.result or {}).get("correct") and not s.dont_know
                   or s.ex.kind in ("open", "recall") and s.result
                   and all((i.get("outcome") or "fail") != "fail" for i in s.result.get("items", []))]
        return {"exercises": len(self.exercises), "graded": len(graded), "correct": len(correct),
                "typos": sum(1 for s in graded if (s.result or {}).get("match") == "typo"),
                "open": sum(1 for s in self.exercises.values() if s.status != "graded")}

    def _touched(self, role: str | None) -> list[dict]:
        hidden = self._learner_secrets() if role == LEARNER else set()
        return [{"ref": r, **v} for r, v in self.touched.items() if r not in hidden]

    @locked
    def teacher_state(self) -> dict:
        self.audit("state")
        open_ex = [self._teacher_exercise(s) for s in self.exercises.values() if s.status != "graded"]
        state = {
            **self.status(),
            "protocol": p.PROTOCOL,
            "new_item_budget": self.new_budget(),
            "open_exercises": open_ex,
            "open_activities": self._open_activities(),
            "pending_proposals": [pr for pr in self.proposals.values() if pr["status"] == "pending"],
            "transcript_tail": self.events_for(TEACHER)[-30:],
            "last_seq": len(self.events),
        }
        self.teacher_seen_seq = max(self.teacher_seen_seq, state["last_seq"])
        return state

    def _open_activities(self) -> list[dict]:
        """Running activities, and finished ones with ungraded goals until
        they are graded or the teacher ends the activity."""
        out = []
        for aid, a in self.activities.items():
            ungraded = getattr(a, "pending", lambda: [])()
            if not a.done or (ungraded and aid not in self.activity_closed):
                entry = {"aid": aid, "type": a.type, "done": a.done, "text": a.describe(TEACHER)}
                if ungraded:
                    entry["ungraded_goals"] = ungraded
                out.append(entry)
        return out

    def learner_state(self) -> dict:
        return {**self.status(LEARNER), "events": self.events_for(LEARNER), "last_seq": len(self.events)}

    def new_budget(self) -> int:
        cap = int(self.settings.get("tutor.new_items_per_15min", 8))
        minutes = (self.goal or {}).get("minutes", 15)
        return max(0, round(cap * max(1.0, minutes / 15)) - len(self.new_refs))

    # --- learner -----------------------------------------------------------------

    def _learner_active(self) -> None:
        self.last_learner_activity = self.clock()
        self._check_open()

    def _check_open(self) -> None:
        if self.ended:
            raise SessionError(409, "ended", "The session has ended")

    @locked
    def start(self, body: p.Start) -> dict:
        self._learner_active()
        self.goal = body.model_dump()
        self.goal_started = self.clock()
        self.time_warned = False
        self._safe(lambda: self.api.update_tutor_session(self.sid, {"goal": self.goal}), default=None)
        self.emit(LEARNER, "start", {"goal": self.goal})
        return self.status(LEARNER)

    @locked
    def message(self, body: p.Message) -> dict:
        self._learner_active()
        e = self.emit(LEARNER, "learner_message", {"text": body.text})
        return {"seq": e.seq}

    @locked
    def answer(self, body: p.Answer) -> dict:
        self._learner_active()
        s = self._exercise(body.exercise_id)
        if s.status != "open":
            raise SessionError(409, "answered", "This exercise was already answered")
        kind = s.ex.kind
        if kind == "mc":
            if not body.selected:
                raise SessionError(400, "validation", "selected is required")
            response = {"selected": body.selected}
            shown = ", ".join(o.text_md for o in s.ex.options if o.id in body.selected)
        elif kind == "match":
            if body.matches is None:
                raise SessionError(400, "validation", "matches is required")
            try:
                response = {"matches": {str(int(left)): s.right_tokens[token] for left, token in body.matches.items()}}
            except (KeyError, ValueError):
                raise SessionError(400, "validation", "unknown match tokens") from None
            shown = "; ".join(
                f"{s.ex.pairs[int(l)].left_md} → {s.ex.pairs[r].right_md}"
                for l, r in response["matches"].items() if int(l) < len(s.ex.pairs) and r < len(s.ex.pairs))
        elif kind in ("text", "open"):
            if body.text is None:
                raise SessionError(400, "validation", "text is required")
            response = {"text": body.text}
            shown = body.text
        else:
            raise SessionError(400, "validation", "recall exercises are revealed and self-graded")
        s.response = response
        if kind in p.KEYED:
            return self._record_keyed(s, response, shown)
        s.status = "answered"
        self.emit(LEARNER, "answered", {"exercise_id": s.id, "kind": kind, "response": response,
                                        "response_md": shown, "awaiting": "grade"},
                  learner={"exercise_id": s.id, "kind": kind, "response_md": shown, "awaiting": "grade"})
        return {"status": "awaiting_grade"}

    @locked
    def dont_know(self, body: p.ExerciseRef) -> dict:
        self._learner_active()
        s = self._exercise(body.exercise_id)
        if s.status != "open":
            raise SessionError(409, "answered", "This exercise was already answered")
        s.dont_know = True
        if s.ex.kind in p.KEYED or s.ex.kind == "recall":
            outcomes = {ref: "fail" for ref in s.ex.items}
            result = self._record(s, outcomes, grader="dont_know", response=None, response_md="(I don't know)")
            s.status = "graded"
            return self._emit_answered(s, result, correct=False)
        s.status = "answered"
        self.emit(LEARNER, "answered", {"exercise_id": s.id, "kind": s.ex.kind, "response": None,
                                        "response_md": "(I don't know)", "dont_know": True, "awaiting": "grade"},
                  learner={"exercise_id": s.id, "kind": s.ex.kind, "response_md": "(I don't know)", "dont_know": True,
                           "awaiting": "grade"})
        return {"status": "awaiting_grade"}

    @locked
    def reveal(self, body: p.ExerciseRef) -> dict:
        self._learner_active()
        s = self._exercise(body.exercise_id)
        if s.ex.kind != "recall":
            raise SessionError(400, "validation", "Only recall exercises are revealed")
        s.revealed = True
        self.emit(LEARNER, "reveal", {"exercise_id": s.id, "reference_md": s.ex.reference_md})
        return {"reference_md": s.ex.reference_md}

    @locked
    def self_grade(self, body: p.SelfGrade) -> dict:
        self._learner_active()
        s = self._exercise(body.exercise_id)
        if s.ex.kind != "recall" or not s.revealed:
            raise SessionError(400, "validation", "Reveal the reference answer first")
        if s.status != "open":
            raise SessionError(409, "answered", "This exercise was already graded")
        outcome = "good" if body.correct else "fail"
        result = self._record(s, {ref: outcome for ref in s.ex.items}, grader="self",
                              response={"self_grade": body.correct}, response_md=None)
        s.status = "graded"
        return self._emit_answered(s, result, correct=body.correct)

    @locked
    def hint_request(self, body: p.ExerciseRef) -> dict:
        self._learner_active()
        s = self._exercise(body.exercise_id)
        self.emit(LEARNER, "hint_request", {"exercise_id": s.id})
        return {"ok": True}

    @locked
    def decide_proposal(self, body: p.ProposalDecision) -> dict:
        self._missing_items.clear()
        self._learner_active()
        proposal = self.proposals.get(body.proposal_id)
        if proposal is None or proposal["status"] != "pending":
            raise SessionError(404, "not_found", "No such pending proposal")
        item = {**proposal["item"], **(body.item or {})}
        result: dict
        if body.action == "dismiss":
            proposal["status"] = "dismissed"
            result = {"created": False}
        elif body.action == "use_existing":
            ref = body.ref or (proposal["candidates"][0]["ref"] if proposal["candidates"] else None)
            if ref is None:
                raise SessionError(400, "validation", "ref is required")
            result = self._api(lambda: self.api.create_item({**item, "same_as": ref, "reason": "learner chose the existing item"}))
            proposal["status"] = "used_existing"
        else:
            body_item = dict(item)
            if body.action == "add_anyway" and proposal["candidates"]:
                body_item["distinct_from"] = [c["ref"] for c in proposal["candidates"]]
                body_item["reason"] = proposal.get("reason") or "learner: a different item"
            elif proposal.get("distinct_from"):
                body_item["distinct_from"] = proposal["distinct_from"]
                body_item["reason"] = proposal.get("reason")
            try:
                result = self.api.create_item(body_item)
            except ApiError as e:
                if e.code == "possible_duplicates":
                    proposal["candidates"] = e.data.get("candidates", [])
                    self.emit(SYSTEM, "proposal", self._proposal_view(proposal))
                    raise SessionError(409, "possible_duplicates", "Similar items appeared; choose again", e.data)
                raise
            proposal["status"] = "added"
            self._after_create(result, proposal.get("dirs", []))
        ref = (result.get("item") or {}).get("ref")
        self.emit(LEARNER, "item_proposal_resolved", {"proposal_id": proposal["id"], "action": body.action, "ref": ref})
        return {"status": proposal["status"], "ref": ref}

    @locked
    def learner_report(self, body: p.LearnerReport) -> dict:
        return self._report(LEARNER, body.category, body.text_md, body.seq, body.include_context)

    @locked
    def learner_end(self) -> dict:
        if not self.ended and self.learner_ended_at is None:
            self.learner_ended_at = self.clock()
            self.emit(LEARNER, "end", {"by": LEARNER})
        return {"ok": True}

    @locked
    def update_settings(self, changes: dict) -> dict:
        self.settings = self._api(lambda: self.api.update_settings(changes))
        self.emit(LEARNER, "settings_changed", {"settings": self.settings})
        return self.settings

    # --- teacher: reading -----------------------------------------------------

    @locked
    def attach(self, body: p.Attach) -> dict:
        connected = self.teacher_last_seen is not None and self.clock() - self.teacher_last_seen < 150
        if self.teacher_attached and connected and not body.takeover:
            raise SessionError(409, "attached", "Another teacher is attached; use --takeover")
        self.teacher_attached = True
        self.teacher_agent = body.agent
        self.audit("attach", body.model_dump())
        self._safe(lambda: self.api.update_tutor_session(self.sid, {"teacher": body.agent or "unknown"}), default=None)
        self.emit(SYSTEM, "status", {"teacher_connected": True, "agent": body.agent})
        return {"protocol": p.PROTOCOL, "sid": self.sid, "goal": self.goal, "last_seq": len(self.events)}

    def profile(self, dir_path: Optional[str]) -> dict:
        self.audit("profile", {"dir": dir_path})
        return self._api(lambda: self.api.profile(self._dir_id(dir_path)))

    def next(self, dir_path: Optional[str], n: int) -> dict:
        self.audit("next", {"dir": dir_path, "n": n})
        dir_path = dir_path if dir_path is not None else self._default_dir()
        return self._api(lambda: self.api.next_items(self._dir_id(dir_path), n=n, new=self.new_budget()))

    def items(self, q: Optional[str], dir_path: Optional[str], space: Optional[str], kind: Optional[str]) -> dict:
        self.audit("items", {"q": q, "dir": dir_path, "space": space, "kind": kind})
        return {"items": self._api(lambda: self.api.list_items(q=q, dir=self._dir_id(dir_path), recursive="1" if dir_path else None,
                                                                space=space, kind=kind, limit=50))}

    def item(self, ref: str) -> dict:
        self.audit("item", {"ref": ref})
        return self._api(lambda: self.api.get_item(ref))

    # --- teacher: acting ------------------------------------------------------

    @locked
    def say(self, body: p.Say) -> dict:
        self._teacher_act("say")
        e = self.emit(TEACHER, "message", {"text_md": body.text_md})
        return {"seq": e.seq}

    @locked
    def introduce(self, body: p.Introduce) -> dict:
        self._teacher_act("introduce", body.model_dump())
        item = self._item(body.ref)
        unseen = item.get("state") is None or item["state"].get("mastery", 0) == 0
        if unseen and item["ref"] not in self.new_refs and self.new_budget() <= 0:
            raise SessionError(409, "new_item_cap", "The new-item budget of this session is used up; stick to review")
        if unseen:
            self.new_refs.add(item["ref"])
        result = self._api(lambda: self.api.record_interaction({
            "uuid": str(uuidlib.uuid4()), "mode": "introduce", "source": self.source, "session_id": self.sid,
            "items": [{"ref": item["ref"]}], "prompt_md": body.text_md,
        }))
        self._touch(result)
        card = {"ref": item["ref"], "label_md": item["label_md"], "gloss_md": item["gloss_md"],
                "body_md": item["body_md"], "kind": item["kind"], "attrs": item.get("attrs") or {},
                "text_md": body.text_md}
        e = self.emit(TEACHER, "item_card", card)
        return {"seq": e.seq}

    @locked
    def ask(self, body: p.Ask) -> dict:
        self._teacher_act("ask", body.model_dump())
        self._require_graded()
        s = self._new_exercise(body.exercise)
        e = self.emit(TEACHER, "exercise", self._teacher_exercise(s), learner=self._learner_exercise(s))
        return {"exercise_id": s.id, "seq": e.seq}

    @locked
    def drill(self, body: p.Drill) -> dict:
        self._teacher_act("drill", {"n": len(body.exercises)})
        self._require_graded()
        drill_id = self._next_id("d")
        states = [self._new_exercise(ex, drill_id) for ex in body.exercises]
        self.drills[drill_id] = [s.id for s in states]
        e = self.emit(TEACHER, "drill", {"drill_id": drill_id, "exercises": [self._teacher_exercise(s) for s in states]},
                      learner={"drill_id": drill_id, "exercises": [self._learner_exercise(s) for s in states]})
        return {"drill_id": drill_id, "exercise_ids": [s.id for s in states], "seq": e.seq}

    @locked
    def grade(self, body: p.Grade) -> dict:
        self._teacher_act("grade", body.model_dump())
        s = self._exercise(body.exercise_id)
        if s.ex.kind != "open":
            raise SessionError(400, "validation", "Only open exercises are graded by the teacher; use override for keyed ones")
        if s.status != "answered":
            raise SessionError(409, "not_answered" if s.status == "open" else "graded",
                               "The exercise has not been answered yet" if s.status == "open" else "Already graded")
        outcomes = self._outcomes_for(s, body.outcomes)
        result = self._record(s, outcomes, grader="teacher", response=s.response,
                              response_md=(s.response or {}).get("text"), feedback_md=body.feedback_md, notes=body.notes)
        s.status = "graded"
        correct = all(o != "fail" for o in outcomes.values())
        partial = not correct and any(o != "fail" for o in outcomes.values())
        self._touch(result)
        e = self.emit(TEACHER, "graded", {"exercise_id": s.id, "outcomes": outcomes, "feedback_md": body.feedback_md,
                                          "correct": correct, "partial": partial, "items": result.get("items", [])},
                      learner={"exercise_id": s.id, "correct": correct, "partial": partial,
                               "feedback_md": body.feedback_md, "reference_md": s.ex.reference_md})
        self._level_changes(result)
        return {"seq": e.seq, "items": result.get("items", [])}

    @locked
    def override(self, body: p.Override) -> dict:
        self._teacher_act("override", body.model_dump())
        s = self._exercise(body.exercise_id)
        if s.uuid is None or s.ex.kind not in p.KEYED:
            raise SessionError(400, "validation", "Only recorded keyed exercises can be overridden")
        if s.overridden:
            raise SessionError(409, "overridden", "An exercise can be overridden once")
        outcomes = self._outcomes_for(s, body.outcomes)
        result = self._api(lambda: self.api.amend_interaction(s.uuid, {
            "items": [{"ref": r, "outcome": o} for r, o in outcomes.items()], "reason": body.reason, "by": "teacher"}))
        s.overridden = True
        self._touch(result)
        correct = all(o != "fail" for o in outcomes.values())
        e = self.emit(TEACHER, "override", {"exercise_id": s.id, "outcomes": outcomes, "reason": body.reason, "correct": correct},
                      learner={"exercise_id": s.id, "reason": body.reason, "correct": correct})
        self._level_changes(result)
        return {"seq": e.seq}

    @locked
    def hint(self, body: p.Hint) -> dict:
        self._teacher_act("hint", body.model_dump())
        s = self._exercise(body.exercise_id)
        if s.status != "open":
            raise SessionError(409, "answered", "Hints are for open exercises")
        s.hinted = True
        e = self.emit(TEACHER, "hint", {"exercise_id": s.id, "text_md": body.text_md})
        return {"seq": e.seq}

    @locked
    def note(self, body: p.Note) -> dict:
        self._teacher_act("note", body.model_dump())
        self._api(lambda: self.api.set_item_flags(body.ref, note=body.text))
        self.emit(TEACHER, "note", {"ref": body.ref, "text": body.text}, learner=None)
        return {"ok": True}

    @locked
    def flag(self, status: str, body: p.Flag) -> dict:
        self._teacher_act(status, body.model_dump())
        item = self._api(lambda: self.api.set_item_flags(body.ref, status=status))
        self.emit(TEACHER, "flag", {"ref": item["ref"], "status": status, "label_md": item["label_md"]})
        return {"ok": True}

    @locked
    def link(self, body: p.Link) -> dict:
        self._teacher_act("link", body.model_dump())
        dir_id = self._dir_id(body.dir)
        self._api(lambda: self.api.link_item_dir(dir_id, body.ref))
        self.emit(TEACHER, "link", {"ref": body.ref, "dir": body.dir}, learner=None)
        return {"ok": True}

    @locked
    def merge(self, body: p.Merge) -> dict:
        self._teacher_act("merge", body.model_dump(by_alias=True))
        payload = {"from": body.from_, "reason": body.reason, "by": "teacher", "session_id": self.sid}
        if self.settings.get("tutor.merge", "propose") == "free":
            merge = self._api(lambda: self.api.merge_items(body.into, payload))
        else:
            merge = self._api(lambda: self.api.suggest_merge({**payload, "into": body.into}))
        self.emit(TEACHER, "merge", {"merge": merge},
                  learner={"merge": merge} if merge.get("status") == "done" else None)
        return merge

    @locked
    def add_item(self, body: p.AddItem) -> dict:
        self._teacher_act("add-item", body.model_dump())
        self._missing_items.clear()   # a 404 seen before may exist now
        mode = self.settings.get("tutor.item_creation", "propose")
        if self.api_version < (0, 11):
            # older APIs ignore dry_run and would create the item at once
            raise SessionError(501, "api_too_old", "Adding items needs pauk API 0.11 or newer; ask the learner to deploy it")
        if mode == "off":
            raise SessionError(403, "item_creation_off", "The learner's settings do not allow adding items")
        item = dict(body.item)
        dirs = [d for d in (self.goal or {}).get("dirs", [])][:1]
        decision: dict = {}
        if body.same_as:
            decision = {"same_as": body.same_as, "reason": body.reason}
        elif body.distinct_from:
            if not body.reason:
                raise SessionError(400, "validation", "distinct_from needs a reason")
            decision = {"distinct_from": body.distinct_from, "reason": body.reason}
        # dry run: exact hit, candidates, or a preview, without writing
        preview = self._api(lambda: self.api.create_item({**item, **decision, "dry_run": True}))
        if not preview.get("would_create"):
            if decision.get("same_as"):
                result = self._api(lambda: self.api.create_item({**item, **decision}))   # writes the alias
                return {"status": "alias", "item": result["item"]}
            return {"status": "exists", "via": preview.get("via"), "item": preview["item"]}
        direct = mode == "free" or (mode == "on_request" and body.requested_seq is not None
                                    and self._is_learner_message(body.requested_seq))
        if direct:
            result = self._api(lambda: self.api.create_item({**item, **decision, "attrs": {**item.get("attrs", {}), "origin": "teacher", "session": self.sid}}))
            self._after_create(result, dirs)
            self.emit(TEACHER, "item_added", {"ref": result["item"]["ref"], "label_md": result["item"]["label_md"],
                                              "requested_seq": body.requested_seq})
            return {"status": "created", "item": result["item"]}
        proposal = {
            "id": self._next_id("p"), "status": "pending",
            "item": {**item, "attrs": {**item.get("attrs", {}), "origin": "teacher", "session": self.sid}},
            "preview": preview["item"], "candidates": [], "distinct_from": decision.get("distinct_from", []),
            "reason": decision.get("reason"), "dirs": dirs,
        }
        self.proposals[proposal["id"]] = proposal
        self.emit(TEACHER, "proposal", self._proposal_view(proposal))
        return {"status": "proposed", "proposal_id": proposal["id"]}

    @locked
    def teacher_report(self, body: p.Report) -> dict:
        self._teacher_act("report", body.model_dump())
        return self._report(TEACHER, body.category, body.text_md, body.seq, True)

    @locked
    def end(self, body: p.End) -> dict:
        self._teacher_act("end")
        self._safe(lambda: self.api.update_tutor_session(self.sid, {
            "ended_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock())), "summary_md": body.summary_md}), default=None)
        self.emit(TEACHER, "summary", {"summary_md": body.summary_md, "touched": self._touched(TEACHER)},
                  learner={"summary_md": body.summary_md, "touched": self._touched(LEARNER)})
        self.finish(TEACHER)
        return {"ok": True}

    @locked
    def finish(self, by: str) -> None:
        if not self.ended:
            self.ended = True
            self.emit(SYSTEM, "ended", {"by": by})

    # --- activities (docs/tutor.md 14) ------------------------------------------

    @property
    def activity_source(self) -> str:
        return "simulation" if self.source == "simulation" else "activity"

    def activity_start(self, body: p.ActivityStart) -> dict:
        # look the refs up before taking the session lock: a content file
        # can name dozens of items, and the API is remote
        try:
            spec = activities.resolve(body.type, body.spec)
            refs = list(spec.get("items") or []) + activities.create(body.type, spec).refs()
        except Exception:  # noqa: BLE001 - the locked part reports the error
            refs = []
        self._prefetch(refs)
        return self._activity_start(body)

    def _prefetch(self, refs: list[str]) -> None:
        for ref in dict.fromkeys(refs):
            if ref in self._item_cache or ref in self._missing_items:
                continue
            try:
                self._item(ref)
            except SessionError:
                self._missing_items.add(ref)
            except ApiError:
                pass   # reported when the activity needs it

    @locked
    def _activity_start(self, body: p.ActivityStart) -> dict:
        self._teacher_act("activity-start", body.model_dump())
        try:
            spec = activities.resolve(body.type, body.spec)
        except ValueError as e:
            raise SessionError(400, "validation", str(e)) from None
        refs = [self._item(ref)["ref"] for ref in spec.get("items", [])]
        try:
            activity = activities.create(body.type, {**spec, "items": refs})
        except ValueError as e:
            raise SessionError(400, "validation", str(e)) from None
        # refs embedded in content need not all be in the profile: evidence
        # for missing ones is skipped, and the teacher learns which they are
        activity.source_spec = body.spec   # what is stored with the evidence (a content ref stays short)
        activity.missing_refs = []
        for ref in activity.refs():
            if ref in self._missing_items:
                activity.missing_refs.append(ref)
                continue
            try:
                self._item(ref)
            except SessionError:
                self._missing_items.add(ref)
                activity.missing_refs.append(ref)
        aid = self._next_id("a")
        self.activities[aid] = activity
        text = activity.describe(TEACHER)
        data = {"aid": aid, "type": activity.type, "view": activity.view(TEACHER), "text": text,
                "missing_items": activity.missing_refs}
        e = self.emit(TEACHER, "activity", data,
                      learner={"aid": aid, "type": activity.type, "view": activity.view(LEARNER),
                               "text": activity.describe(LEARNER)},
                      teacher={"aid": aid, "type": activity.type, "text": text, "missing_items": activity.missing_refs})
        out = {"aid": aid, "seq": e.seq, "text": text}
        if activity.missing_refs:
            out["missing_items"] = activity.missing_refs
            out["note"] = ("These items are not in the profile, so the activity records no evidence for them; "
                           "add them with `pauk teach add-item` if the learner should learn them.")
        return out

    @locked
    def activity_act(self, role: str, body: p.ActivityAct) -> dict:
        if role == LEARNER:
            self._learner_active()
        else:
            self._teacher_act("activity-act", body.model_dump())
        activity = self._activity(body.aid)
        self._flush_activity_writes()   # retry evidence a failed write left behind
        try:
            summary = activity.act(body.action, role)
        except ValueError as e:
            raise SessionError(400, "invalid_action", str(e)) from None
        self._activity_update(role, body.aid, activity, body.action, summary)
        if role == LEARNER:
            return {"summary": summary, **_summary_msg(summary), "state": activity.state(LEARNER),
                    "text": activity.describe(LEARNER)}
        # compact for the teacher: what changed and the description; `activity observe` has the full state
        return {"summary": summary, "done": activity.done, "text": activity.describe(TEACHER)}

    def _activity_update(self, role: str, aid: str, activity, action: dict, summary: str) -> None:
        text = activity.describe(TEACHER)
        # a teacher's grade carries per-item outcomes: the learner sees only the summary
        learner_action = action if role == LEARNER else {k: v for k, v in action.items() if k != "grade"}
        self.emit(role, "activity_update",
                  {"aid": aid, "action": action, "summary": summary, "state": activity.state(TEACHER), "text": text},
                  learner={"aid": aid, "action": learner_action, "summary": summary, **_summary_msg(summary),
                           "state": activity.state(LEARNER), "text": activity.describe(LEARNER)},
                  teacher={"aid": aid, "action": action, "summary": summary, "done": activity.done, "text": text})
        for ev in getattr(activity, "evidence", lambda: [])():
            self._queue_activity_write(aid, activity, ev["items"], ev["mode"], ev["detail"],
                                       learner=ev.get("learner"))
        if activity.done and aid not in self.activity_final:
            self.activity_final.add(aid)
            result = activity.result()
            outcomes = result.get("items")
            if outcomes is None:
                outcomes = {ref: result["outcome"] for ref in activity.spec.get("items") or []}
            self._queue_activity_write(aid, activity, outcomes, result.get("mode", "produce"), result["detail"],
                                       final=result)
        self._flush_activity_writes()

    @locked
    def activity_observe(self, aid: str) -> dict:
        self.audit("activity-observe", {"aid": aid})
        activity = self._activity(aid)
        out = {"aid": aid, "type": activity.type, "state": activity.state(TEACHER), "text": activity.describe(TEACHER),
               "missing_items": activity.missing_refs}
        pending = [w for w in self.activity_writes if w["aid"] == aid]
        if pending:
            out["unrecorded"] = len(pending)
        return out

    @locked
    def activity_end(self, body: p.ActivityRef) -> dict:
        self._teacher_act("activity-end", body.model_dump())
        activity = self._activity(body.aid)
        self.activity_closed.add(body.aid)   # no more reminders of ungraded goals
        if not activity.done:
            # a type may end differently from a give-up (map_labels: untouched markers are no evidence)
            end = getattr(activity, "end", None)
            if end:
                summary = end()
            else:
                activity.act({"give_up": True}, TEACHER)
                summary = Msg("activity.ended_by_teacher", "ended by the teacher")
            self._activity_update(TEACHER, body.aid, activity, {"end": True}, summary)
        else:
            self._flush_activity_writes()   # a retry of evidence that failed to record
        pending = [w for w in self.activity_writes if w["aid"] == body.aid]
        return {"ok": not pending, **({"unrecorded": len(pending)} if pending else {})}

    def _activity(self, aid: str):
        if aid not in self.activities:
            raise SessionError(404, "not_found", f"No activity {aid}")
        return self.activities[aid]

    def _queue_activity_write(self, aid: str, activity, outcomes: dict, mode: str, detail: dict,
                              learner: dict | None = None, final: dict | None = None) -> None:
        """Turn one graded activity event into interactions (with fixed
        uuids, so a retry never records twice) and queue them.

        Activities follow the exercise rules for new items: evidence on an
        item the learner has never seen spends the new-item budget (none
        left: no evidence), and a first contact that failed is recorded as
        `introduce` (the learner has now met the word), not as `fail`."""
        graded, introduced, skipped = [], [], []
        for ref, outcome in outcomes.items():
            if ref in activity.missing_refs:
                continue
            item = self._item(ref)
            ref = item["ref"]
            unseen = (item.get("state") or {}).get("mastery", 0) == 0 and ref not in self.new_refs
            if unseen:
                if self.new_budget() <= 0:
                    skipped.append(ref)
                    continue
                self.new_refs.add(ref)
                if outcome == "fail":
                    introduced.append(ref)
                    continue
            graded.append({"ref": ref, "outcome": outcome})
        bodies = []
        if graded:
            bodies.append({"uuid": str(uuidlib.uuid4()), "mode": mode, "source": self.activity_source,
                           "session_id": self.sid, "grader": f"{activity.type}@1",
                           "exercise": {"kind": "activity", "type": activity.type, "spec": activity.source_spec},
                           "response": detail, "items": graded})
        if introduced:
            bodies.append({"uuid": str(uuidlib.uuid4()), "mode": "introduce", "source": self.activity_source,
                           "session_id": self.sid, "items": [{"ref": r} for r in introduced],
                           "prompt_md": f"Met in the {activity.type} activity"})
        self.activity_writes.append({"aid": aid, "bodies": bodies, "results": [], "mode": mode,
                                     "outcomes": dict(outcomes), "introduced": introduced, "skipped_new": skipped,
                                     "learner": learner, "final": final})

    def _flush_activity_writes(self) -> None:
        """Record every queued write; a failed one stays queued for the
        next activity action or `activity end`."""
        failed, errors = [], []
        for write in list(self.activity_writes):
            try:
                while len(write["results"]) < len(write["bodies"]):
                    body = write["bodies"][len(write["results"])]
                    write["results"].append(self.api.record_interaction(body))
            except Exception as e:  # noqa: BLE001 - any failure keeps the write for a retry
                failed.append(write)
                errors.append(str(e))
                continue
            self._activity_recorded(write)
        self.activity_writes = failed
        if failed:
            self.emit(SYSTEM, "activity_error", {"message": f"recording activity evidence failed: {errors[0]}",
                                                 "unrecorded": len(failed),
                                                 "retry": "on the next activity action or `activity end`"},
                      learner=None)

    def _activity_recorded(self, write: dict) -> None:
        aid, activity = write["aid"], self.activities[write["aid"]]
        items = []
        for result in write["results"]:
            self._touch(result)
            items += result.get("items", [])
        final = write["final"]
        if final is None:
            data = {"aid": aid, "mode": write["mode"], "outcomes": write["outcomes"], "items": items}
            if write["introduced"]:
                data["introduced"] = write["introduced"]
            if write["skipped_new"]:
                data["skipped_new"] = write["skipped_new"]
            # the learner gets an aggregate, never per-item outcomes or refs
            self.emit(SYSTEM, "activity_graded", data, learner={"aid": aid, **(write["learner"] or {"mode": write["mode"]})})
        for result in write["results"]:
            self._level_changes(result)
        if final is not None and aid not in self.activity_done_sent:
            self.activity_done_sent.add(aid)
            data = {"aid": aid, "outcome": final["outcome"], **final["detail"], "items": items}
            if write["skipped_new"]:
                data["skipped_new"] = write["skipped_new"]
            ungraded = getattr(activity, "pending", lambda: [])()
            if ungraded:
                data["ungraded_goals"] = ungraded
            self.emit(SYSTEM, "activity_done", data,
                      learner={"aid": aid, "outcome": final["outcome"], **final.get("learner", final["detail"])})

    # --- observer --------------------------------------------------------------

    @locked
    def annotate(self, body: p.Annotate) -> dict:
        e = self.emit(OBSERVER, "annotation", body.model_dump(), learner=None, observer_only=True)
        return {"seq": e.seq}

    @locked
    def observer_report(self, body: p.Report) -> dict:
        return self._report(OBSERVER, body.category, body.text_md, body.seq, True)

    # --- clock-driven ------------------------------------------------------------

    @locked
    def tick(self, idle_limit: float = 600) -> None:
        """Called periodically by the host: time warning and idle end."""
        if self.ended:
            return
        now = self.clock()
        if self.goal and not self.time_warned and self.goal_started is not None:
            if now >= self.goal_started + self.goal["minutes"] * 60 - 120:
                self.time_warned = True
                self.emit(SYSTEM, "time_warning", {"minutes_left": 2})
        if self.learner_ended_at is not None and now - self.learner_ended_at > 120:
            self.finish(SYSTEM)   # the teacher did not wrap up in time
            return
        if now - self.last_learner_activity > idle_limit:
            self.emit(SYSTEM, "idle", {"idle_s": round(now - self.last_learner_activity)})
            self.finish(SYSTEM)

    @locked
    def set_teacher_model(self, model: str) -> None:
        self.teacher_model = model
        self.emit(SYSTEM, "status", {"teacher_model": model})

    def set_agent_running(self, running: bool, detail: str = "") -> None:
        self.agent_running = running
        if not running:
            self.teacher_last_seen = None
            self.teacher_attached = False
        self.emit(SYSTEM, "status", {"agent_running": running, "teacher_connected": running and self.teacher_attached,
                                     "detail": detail})

    # --- internals ------------------------------------------------------------------

    WRAP_UP = ("say", "note", "report", "end")

    def _teacher_act(self, command: str, args: dict | None = None) -> None:
        self._check_open()
        if self.learner_ended_at is not None and command not in self.WRAP_UP:
            raise SessionError(409, "learner_ended",
                               "The learner has ended the session: say goodbye if you like, then `pauk teach end` with a summary")
        self.audit(command, args)

    def _require_graded(self) -> None:
        pending = [s.id for s in self.exercises.values() if s.status == "answered" and s.ex.kind == "open"]
        if pending:
            raise SessionError(409, "grade_first", f"Grade the answered exercise(s) {', '.join(pending)} first")

    def _new_exercise(self, ex: p.Exercise, drill_id: str | None = None) -> ExerciseState:
        refs = []
        for ref in ex.items:
            item = self._item(ref)
            unseen = item.get("state") is None or item["state"].get("mastery", 0) == 0
            if unseen and item["ref"] not in self.new_refs:
                # testing an unseen item spends the new-item budget like introducing it
                if self.new_budget() <= 0:
                    raise SessionError(409, "new_item_cap", f"{item['ref']} is new and the new-item budget is used up")
                self.new_refs.add(item["ref"])
            refs.append(item["ref"])
        ex = ex.model_copy(update={"items": refs})
        s = ExerciseState(self._next_id("ex"), ex, drill_id)
        if ex.kind == "match":
            s.right_tokens = {secrets.token_hex(3): i for i in range(len(ex.pairs))}
        self.exercises[s.id] = s
        return s

    def _learner_exercise(self, s: ExerciseState) -> dict:
        ex = s.ex
        view: dict = {"exercise_id": s.id, "kind": ex.kind, "mode": ex.mode, "prompt_md": ex.prompt_md,
                      "drill_id": s.drill_id}
        if ex.kind == "mc":
            view["options"] = [o.model_dump() for o in ex.options]
            view["multiple"] = len(ex.correct) > 1
        if ex.kind == "match":
            view["lefts"] = [{"index": i, "left_md": pair.left_md} for i, pair in enumerate(ex.pairs)]
            rights = [{"token": t, "right_md": ex.pairs[i].right_md} for t, i in s.right_tokens.items()]
            self.rng.shuffle(rights)
            view["rights"] = rights
        return view

    def _teacher_exercise(self, s: ExerciseState) -> dict:
        return {"exercise_id": s.id, "status": s.status, "hinted": s.hinted, "drill_id": s.drill_id,
                **s.ex.model_dump(exclude_none=True)}

    def _exercise(self, exercise_id: str) -> ExerciseState:
        s = self.exercises.get(exercise_id)
        if s is None:
            raise SessionError(404, "not_found", f"No exercise {exercise_id}")
        return s

    def _item(self, ref: str) -> dict:
        if ref not in self._item_cache:
            try:
                item = self.api.get_item(ref)
            except ApiError as e:
                if e.status == 404:
                    raise SessionError(400, "unknown_item", f"Item {ref} is not in the profile; search with `pauk teach items --q`") from None
                raise
            self._item_cache[ref] = item
            self._item_cache[item["ref"]] = item
        return self._item_cache[ref]

    def _outcomes_for(self, s: ExerciseState, outcomes: dict[str, str]) -> dict[str, str]:
        resolved = {self._item(ref)["ref"]: o for ref, o in outcomes.items()}
        if set(resolved) != set(s.ex.items):
            raise SessionError(400, "validation", f"Outcomes must cover exactly the exercise items: {', '.join(s.ex.items)}")
        return resolved

    def _exercise_payload(self, s: ExerciseState) -> dict:
        return s.ex.model_dump(exclude_none=True, exclude={"items", "mode", "card_id"})

    def _record_keyed(self, s: ExerciseState, response: dict, shown: str) -> dict:
        body = {
            "uuid": str(uuidlib.uuid4()), "mode": s.ex.mode, "source": self.source, "session_id": self.sid,
            "exercise": self._exercise_payload(s), "response": response, "hinted": s.hinted,
            "prompt_md": s.ex.prompt_md, "response_md": shown, "items": [{"ref": r} for r in s.ex.items],
        }
        if s.ex.card_id is not None:
            body["card_id"] = s.ex.card_id
        result = self._api(lambda: self.api.record_interaction(body))
        s.uuid = body["uuid"]
        s.status = "graded"
        s.result = result
        return self._emit_answered(s, result, correct=bool(result.get("correct")), response_md=shown)

    def _record(self, s: ExerciseState, outcomes: dict, grader: str, response: dict | None,
                response_md: str | None, feedback_md: str | None = None, notes: dict | None = None) -> dict:
        body = {
            "uuid": str(uuidlib.uuid4()), "mode": s.ex.mode, "source": self.source, "session_id": self.sid,
            "exercise": self._exercise_payload(s), "hinted": s.hinted, "grader": grader,
            "prompt_md": s.ex.prompt_md, "response_md": response_md, "feedback_md": feedback_md,
            "items": [{"ref": r, "outcome": o, **({"note": notes[r]} if notes and r in notes else {})}
                      for r, o in outcomes.items()],
        }
        if response is not None:
            body["response"] = response
        if s.ex.card_id is not None:
            body["card_id"] = s.ex.card_id
        result = self._api(lambda: self.api.record_interaction(body))
        s.uuid = body["uuid"]
        s.result = result
        return result

    def _emit_answered(self, s: ExerciseState, result: dict, correct: bool, response_md: str | None = None) -> dict:
        self._touch(result)
        expected = self._expected_md(s)
        self.emit(LEARNER, "answered", {
            "exercise_id": s.id, "kind": s.ex.kind, "drill_id": s.drill_id, "correct": correct,
            "match": result.get("match"), "response": s.response, "dont_know": s.dont_know,
            "expected_md": expected, "items": result.get("items", []),
            "response_md": response_md,
        }, learner={"exercise_id": s.id, "kind": s.ex.kind, "drill_id": s.drill_id, "correct": correct,
                    "match": result.get("match"), "expected_md": expected, "response": s.response,
                    "response_md": response_md})
        self._level_changes(result)
        if s.drill_id is not None:
            ids = self.drills[s.drill_id]
            if all(self.exercises[i].status == "graded" for i in ids):
                self.emit(SYSTEM, "drill_done", {
                    "drill_id": s.drill_id,
                    "results": [{"exercise_id": i, "items": self.exercises[i].ex.items,
                                 "correct": bool((self.exercises[i].result or {}).get("correct")) and not self.exercises[i].dont_know,
                                 "match": (self.exercises[i].result or {}).get("match")} for i in ids],
                }, learner={"drill_id": s.drill_id})
        return {"correct": correct, "match": result.get("match"), "expected_md": expected}

    @staticmethod
    def _expected_md(s: ExerciseState) -> Optional[str]:
        ex = s.ex
        if ex.kind == "mc":
            return ", ".join(o.text_md for o in ex.options if o.id in ex.correct)
        if ex.kind == "match":
            return "; ".join(f"{pair.left_md} → {pair.right_md}" for pair in ex.pairs)
        if ex.kind == "text":
            return " / ".join(ex.accepted)
        return ex.reference_md

    def _touch(self, result: dict) -> None:
        for entry in result.get("items", []):
            state = entry.get("state") or {}
            ref = entry["ref"]
            current = self.touched.get(ref)
            label = self._item_cache.get(ref, {}).get("label_md", ref)
            if current is None:
                self.touched[ref] = {"label_md": label, "before": entry.get("mastery_before", state.get("mastery", 0)),
                                     "now": state.get("mastery", 0)}
                if entry.get("mastery_before", 1) == 0:
                    self.new_refs.add(ref)
            else:
                current["now"] = state.get("mastery", current["now"])

    def _level_changes(self, result: dict) -> None:
        changes = [{"ref": e["ref"], "before": e["mastery_before"], "now": (e.get("state") or {}).get("mastery", 0),
                    "label_md": self._item_cache.get(e["ref"], {}).get("label_md", e["ref"])}
                   for e in result.get("items", [])
                   if "mastery_before" in e and e["mastery_before"] != (e.get("state") or {}).get("mastery", 0)]
        if changes:
            hidden = self._learner_secrets()
            shown = [c for c in changes if c["ref"] not in hidden]
            self.emit(SYSTEM, "level_change", {"changes": changes}, learner={"changes": shown} if shown else None)

    def _learner_secrets(self) -> set[str]:
        """Item refs that would give away an activity answer the learner
        has not seen yet (an unnamed object, an unlabelled marker)."""
        return {ref for a in self.activities.values() for ref in getattr(a, "secret_refs", set)()}

    def _after_create(self, result: dict, dirs: list[str]) -> None:
        item = result.get("item") or {}
        for path in dirs:
            self._safe(lambda: self.api.link_item_dir(self._dir_id(path), item["ref"]), default=None)

    def _proposal_view(self, proposal: dict) -> dict:
        return {"proposal_id": proposal["id"], "status": proposal["status"], "item": proposal["preview"],
                "candidates": proposal["candidates"]}

    def _is_learner_message(self, seq: int) -> bool:
        return 0 < seq <= len(self.events) and self.events[seq - 1].type == "learner_message"

    def _report(self, reporter: str, category: str, text_md: str, seq: Optional[int], include_context: bool) -> dict:
        context: dict = {}
        if include_context:
            around = self.events_for(OBSERVER)
            if seq is not None:
                around = [e for e in around if abs(e["seq"] - seq) <= 10]
            else:
                around = around[-20:]
            context = {"events": around, "goal": self.goal, "settings": self.settings,
                       "protocol": p.PROTOCOL, "teacher_agent": self.teacher_agent}
            try:
                from pauk import __version__
                context["cli_version"] = __version__
            except ImportError:  # pragma: no cover
                pass
        body = {"session_uid": self.sid, "seq": seq, "reporter": reporter, "category": category,
                "text_md": text_md, "context": context}
        try:
            report_id = self.api.create_report(body).get("id")
            stored = "api"
        except ApiError as e:
            if e.status == 400:
                raise SessionError(e.status, e.code, str(e)) from None
            # older API without /reports, a too large context, a server error:
            # keep the report locally rather than lose it
            self._local_report(body)
            report_id, stored = None, "local"
        except Exception:   # network failure
            self._local_report(body)
            report_id, stored = None, "local"
        self.emit(reporter, "report", {"category": category, "text_md": text_md, "about_seq": seq, "stored": stored},
                  learner={"category": category, "stored": stored} if reporter == LEARNER else None)
        # never echo the context: it holds hidden exercise keys
        return {"stored": stored, "id": report_id}

    def _local_report(self, body: dict) -> dict:
        """API without /reports (not deployed yet): keep the report locally."""
        path = (self.store.parent if self.store else Path.home() / ".local" / "share" / "pauk") / "reports.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(body, ensure_ascii=False) + "\n")
        return {**body, "path": str(path)}

    def _dir_id(self, path: Optional[str]) -> Optional[int]:
        if not path:
            return None
        try:
            return self.api.resolve_dir(path)["id"]
        except ApiError as e:
            if e.status == 404:
                raise SessionError(400, "unknown_dir", f"No subject directory '{path}'") from None
            raise

    def _default_dir(self) -> Optional[str]:
        dirs = (self.goal or {}).get("dirs") or []
        return dirs[0] if dirs else None

    def _api(self, call: Callable[[], Any]) -> Any:
        try:
            return call()
        except ApiError as e:
            raise SessionError(e.status, e.code, str(e).split(": ", 1)[-1], e.data) from None

    @staticmethod
    def _version(text: str) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in text.split("."))
        except ValueError:
            return (0,)

    @staticmethod
    def _safe(call: Callable[[], Any], default: Any) -> Any:
        """For optional calls (tutor-session bookkeeping on an older API)."""
        try:
            return call()
        except ApiError:
            return default
