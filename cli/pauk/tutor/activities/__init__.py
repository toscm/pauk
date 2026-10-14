"""Activities: stateful, turn-based exercises inside a tutor session
(docs/tutor.md 14). Rules are code; every participant acts through
the same `act` call, and `describe` gives an LLM everything it needs
without pixels. One module per type: route, map_labels, town.

An activity type implements:

- `__init__(spec)`: validate the spec (raise ValueError);
- `view(role)`: the full state as JSON for renderers, filtered per role
  (the learner never sees answer keys, teacher and observer do);
- `state(role)`: the part of the view that changes with actions;
- `describe(role)`: a short text an agent can act on, filtered the same way;
- `act(action, role)`: apply one action, return a short summary (raise ValueError);
- `refs()`: every item ref the activity can produce evidence for;
- `evidence()` (optional): graded events produced since the last call,
  `[{"mode", "items": {ref: outcome}, "detail"}]`, recorded at once;
- `done` and `result()`: when finished, `{"outcome", "detail"}` plus
  optionally `"items": {ref: outcome}` (and `"mode"`); without `items`
  the outcome is recorded against the spec's `items`.

Specs can be inline JSON or a reference to bundled content:
`{"ref": "italian-town"}` loads `pauk/data/activities/italian-town.json`
(a copy of `content/activities/`, docs/tutor.md 13); other keys of the
inline spec override the content's.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources

from pauk.tutor.activities.map_labels import MapLabelsActivity
from pauk.tutor.activities.route import RouteActivity
from pauk.tutor.activities.town import TownActivity

TYPES = {cls.type: cls for cls in (RouteActivity, MapLabelsActivity, TownActivity)}
CONTENT_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@lru_cache(maxsize=16)
def _content(name: str) -> str:
    if not CONTENT_NAME.match(name):
        raise ValueError(f"bad content name '{name}'")
    path = resources.files("pauk.data").joinpath("activities", f"{name}.json")
    if not path.is_file():
        raise ValueError(f"no activity content '{name}' (known: {', '.join(content_names())})")
    return path.read_text(encoding="utf-8")


def content_names() -> list[str]:
    folder = resources.files("pauk.data").joinpath("activities")
    return sorted(p.name[:-5] for p in folder.iterdir() if p.name.endswith(".json"))


def resolve(type_: str, spec: dict) -> dict:
    """Inline spec, or bundled content named by `ref` with overrides."""
    if type_ not in TYPES:
        raise ValueError(f"unknown activity type '{type_}' (known: {', '.join(TYPES)})")
    if not isinstance(spec, dict):
        raise ValueError("spec must be a JSON object or a content name")
    if "ref" not in spec:
        return spec
    content = json.loads(_content(str(spec["ref"])))
    if content.get("type") != type_:
        raise ValueError(f"content '{spec['ref']}' is a {content.get('type')} activity, not {type_}")
    return {**content["spec"], **{k: v for k, v in spec.items() if k != "ref"}, "ref": spec["ref"]}


def create(type_: str, spec: dict):
    spec = resolve(type_, spec)
    return TYPES[type_](spec)
