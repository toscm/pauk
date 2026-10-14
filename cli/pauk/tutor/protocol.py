"""The local session protocol (docs/tutor.md section 9).

One source of truth for the shapes exchanged between the session
host, the browser (learner), the teacher agent (`pauk teach`) and
the observer. Pydantic models validate every teacher action, and
`pauk teach help --json` prints their JSON schemas.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# Bumped on incompatible changes; `pauk teach attach` refuses a mismatch.
PROTOCOL = 2

Kind = Literal["mc", "match", "text", "open", "recall"]
Mode = Literal["recognize", "recall", "produce", "explain"]
Outcome = Literal["fail", "hard", "good", "easy"]
KEYED = ("mc", "match", "text")
DEFAULT_MODE = {"mc": "recognize", "match": "recognize", "text": "recall", "open": "produce", "recall": "recall"}

Category = Literal["bug", "content", "teacher", "ux", "idea"]


class Option(BaseModel):
    id: str = Field(min_length=1, max_length=16)
    text_md: str


class Pair(BaseModel):
    left_md: str
    right_md: str


class Exercise(BaseModel):
    """What the teacher asks. Keys (correct, accepted, reference_md)
    never reach the learner before the answer."""

    kind: Kind
    mode: Optional[Mode] = None
    items: list[str] = Field(min_length=1, max_length=5, description="item refs (space/key) this exercise tests")
    prompt_md: str = Field(min_length=1)
    options: Optional[list[Option]] = Field(default=None, min_length=2, max_length=6)
    correct: Optional[list[str]] = None
    pairs: Optional[list[Pair]] = Field(default=None, min_length=2, max_length=8)
    accepted: Optional[list[str]] = Field(default=None, min_length=1)
    reference_md: Optional[str] = None
    card_id: Optional[int] = None

    @model_validator(mode="after")
    def _check(self) -> "Exercise":
        if self.mode is None:
            self.mode = DEFAULT_MODE[self.kind]
        if self.kind == "mc":
            if not self.options or not self.correct:
                raise ValueError("mc needs options and correct")
            ids = [o.id for o in self.options]
            if len(set(ids)) != len(ids):
                raise ValueError("mc option ids must be unique")
            if not set(self.correct) <= set(ids):
                raise ValueError("mc correct ids must be among the option ids")
        if self.kind == "match" and not self.pairs:
            raise ValueError("match needs pairs")
        if self.kind == "text" and not self.accepted:
            raise ValueError("text needs accepted answers")
        if self.kind == "recall" and not self.reference_md:
            raise ValueError("recall needs reference_md")
        if len(set(self.items)) != len(self.items):
            raise ValueError("items must be distinct")
        return self


# --- teacher actions ---------------------------------------------------------

class Attach(BaseModel):
    takeover: bool = False
    agent: Optional[str] = Field(default=None, description="who is teaching, e.g. claude-code")


class Say(BaseModel):
    text_md: str = Field(min_length=1)


class Introduce(BaseModel):
    ref: str
    text_md: Optional[str] = None


class Ask(BaseModel):
    exercise: Exercise


class Drill(BaseModel):
    exercises: list[Exercise] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def _keyed(self) -> "Drill":
        if any(e.kind not in KEYED for e in self.exercises):
            raise ValueError("drills contain only keyed exercises (mc, match, text)")
        return self


class Grade(BaseModel):
    exercise_id: str
    outcomes: dict[str, Outcome] = Field(description="item ref -> outcome, covering every item of the exercise")
    feedback_md: Optional[str] = None
    notes: dict[str, str] = Field(default_factory=dict, description="item ref -> per-item note")


class Override(BaseModel):
    exercise_id: str
    outcomes: dict[str, Outcome]
    reason: str = Field(min_length=3)


class Hint(BaseModel):
    exercise_id: str
    text_md: str = Field(min_length=1)


class Note(BaseModel):
    ref: str
    text: str


class Flag(BaseModel):
    ref: str


class Link(BaseModel):
    ref: str
    dir: str = Field(description="subject directory path, e.g. bioinformatics")


class Merge(BaseModel):
    into: str
    from_: str = Field(alias="from")
    reason: str = Field(min_length=3)

    model_config = {"populate_by_name": True}


class AddItem(BaseModel):
    item: dict = Field(description="space, kind, label_md, gloss_md, body_md?, key? (omit for word/phrase/term)")
    same_as: Optional[str] = None
    distinct_from: list[str] = Field(default_factory=list)
    reason: Optional[str] = None
    requested_seq: Optional[int] = Field(default=None, description="seq of the learner message asking to learn it")


class ActivityStart(BaseModel):
    type: str = Field(description="activity type: route, map_labels or town")
    spec: dict = Field(description='inline, e.g. {"start": "muenchen", "goal": "berlin", "items": [...]}, '
                                   'or bundled content with overrides, e.g. {"ref": "italian-town"}')


class ActivityAct(BaseModel):
    aid: str
    action: dict = Field(description='e.g. {"drive": "nuernberg"}, {"label": {"marker": 3, "name": "Leipzig"}}, '
                                     '{"go_to": "bakery"}, {"npc": "baker", "say": "..."}; observe lists the actions')


class ActivityRef(BaseModel):
    aid: str


class Report(BaseModel):
    category: Category
    text_md: str = Field(min_length=1)
    seq: Optional[int] = None


class End(BaseModel):
    summary_md: str = Field(min_length=1)


# --- learner actions ---------------------------------------------------------

class Start(BaseModel):
    dirs: list[str] = Field(default_factory=list, description="subject directory paths")
    mode: Literal["learn", "review", "mixed", "chat"] = "mixed"
    minutes: int = Field(default=15, ge=5, le=120)


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class Answer(BaseModel):
    exercise_id: str
    selected: Optional[list[str]] = None
    matches: Optional[dict[str, str]] = None
    text: Optional[str] = None


class ExerciseRef(BaseModel):
    exercise_id: str


class SelfGrade(BaseModel):
    exercise_id: str
    correct: bool


class ProposalDecision(BaseModel):
    proposal_id: str
    action: Literal["add", "add_anyway", "use_existing", "dismiss"]
    ref: Optional[str] = Field(default=None, description="the existing item for use_existing")
    item: Optional[dict] = Field(default=None, description="edited fields for add")


class LearnerReport(BaseModel):
    category: Category
    text_md: str = Field(min_length=1, max_length=20000)
    seq: Optional[int] = None
    include_context: bool = True


class Annotate(BaseModel):
    seq: int
    text: str = Field(min_length=1)
    tag: Optional[str] = None


TEACHER_ACTIONS: dict[str, type[BaseModel]] = {
    "attach": Attach, "say": Say, "introduce": Introduce, "ask": Ask, "drill": Drill,
    "grade": Grade, "override": Override, "hint": Hint, "note": Note, "focus": Flag,
    "suspend": Flag, "link": Link, "merge": Merge, "add-item": AddItem, "report": Report, "end": End,
    "activity-start": ActivityStart, "activity-act": ActivityAct, "activity-end": ActivityRef,
}


def schemas() -> dict:
    return {name: model.model_json_schema(by_alias=True) for name, model in TEACHER_ACTIONS.items()}
