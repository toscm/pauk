"""Courses: a subject split into stages (A1 … C2) and units, shown as a
level map (docs/tutor.md 9.6).

A curriculum is bundled content (`content/curricula/<name>.json`,
copied to `pauk/data/curricula/`). Every unit is a directory
`<root>/<stage>/<unit>` on the server holding the unit's items, so
progress, selection (`next`) and new items added by the teacher all
work through ordinary subject directories. `pauk import` of a
curriculum file creates the directories and links the listed items.

Stars come from the memory model, never from a separate score:

- ★ when half of the unit's items are at least "learning" (mastery ≥ 3,
  i.e. answered correctly with some stability),
- ★★ (passed) at 80 %,
- ★★★ when 80 % are "known" (mastery ≥ 4, stable for weeks).

An exam asks every item once, so passing it with 80 % gives ★★ by the
same rule. A unit whose items are mostly due again needs a refresh.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, Callable, Optional

from pauk.client import ApiError

LEARNED = 3          # mastery "learning" and above
KNOWN = 4
MIN_GENERATED = 10   # a unit the teacher fills needs this many items before it earns stars


def names() -> list[str]:
    folder = resources.files("pauk.data").joinpath("curricula")
    return sorted(p.name[:-5] for p in folder.iterdir() if p.name.endswith(".json"))


def load(name: str) -> dict:
    if name not in names():
        raise KeyError(name)
    return json.loads(resources.files("pauk.data").joinpath("curricula", f"{name}.json").read_text(encoding="utf-8"))


def unit_path(curriculum: dict, stage_id: str, unit_id: str) -> str:
    return f"{curriculum['root']}/{stage_id}/{unit_id}"


def find_unit(curriculum: dict, stage_id: str, unit_id: str) -> tuple[dict, dict]:
    for stage in curriculum["stages"]:
        if stage["id"] == stage_id:
            for unit in stage["units"]:
                if unit["id"] == unit_id:
                    return stage, unit
    raise KeyError(f"{stage_id}/{unit_id}")


def stars(progress: Optional[dict], generated: bool) -> dict:
    """Stars, the learned share and whether a refresh is due, from a
    `/profile/dirs` entry (None: the unit has no directory yet)."""
    n = (progress or {}).get("items", 0)
    by = {int(k): v for k, v in ((progress or {}).get("by_mastery") or {}).items()}
    learned = sum(v for k, v in by.items() if k >= LEARNED)
    known = sum(v for k, v in by.items() if k >= KNOWN)
    seen = n - by.get(0, 0)
    due = (progress or {}).get("due", 0)
    count = 0
    if n and not (generated and n < MIN_GENERATED):
        count = 3 if known >= 0.8 * n else 2 if learned >= 0.8 * n else 1 if learned >= 0.5 * n else 0
    return {"stars": count, "items": n, "seen": seen, "learned": learned, "known": known, "due": due,
            "share": round(learned / n, 2) if n else 0.0,
            "refresh": count >= 1 and due >= max(2, 0.25 * n)}


def level_map(api, name: str) -> dict:
    """The curriculum with progress per unit and the recommended next unit."""
    curriculum = load(name)
    progress: dict[str, dict] = {}
    imported = True
    try:
        root = api.resolve_dir(curriculum["root"])
        progress = {d["path"]: d for d in api.profile_dirs(root["id"])}
    except ApiError as e:
        if e.code != "not_found":
            raise
        imported = False
    recommended = None
    stages = []
    for stage in curriculum["stages"]:
        units = []
        for unit in stage["units"]:
            generated = not unit["items"]
            entry = {k: unit[k] for k in ("id", "title", "can_do") if k in unit}
            entry.update(planned=len(unit["items"]), generated=generated, activity=unit.get("activity"),
                         **stars(progress.get(f"{stage['id']}/{unit['id']}"), generated))
            if recommended is None and entry["stars"] < 2:
                recommended = {"stage": stage["id"], "unit": unit["id"]}
            units.append(entry)
        passed = sum(1 for u in units if u["stars"] >= 2)
        stages.append({"id": stage["id"], "title": stage["title"], "description": stage.get("description"),
                       "units": units, "passed": passed})
    return {"id": curriculum["curriculum"], "title": curriculum["title"], "space": curriculum.get("space"),
            "imported": imported, "stages": stages, "recommended": recommended}


def ensure_path(api, path: str) -> int:
    """The directory id of `path`, creating missing parts (mkdir -p)."""
    parent_id = None
    parts = path.split("/")
    for i in range(1, len(parts) + 1):
        sub = "/".join(parts[:i])
        try:
            parent_id = api.resolve_dir(sub)["id"]
        except ApiError as e:
            if e.code != "not_found":
                raise
            parent_id = api.create_dir(parts[i - 1], parent_id)["id"]
    return parent_id


def import_curriculum(api, data: dict, echo: Callable[[str], Any] = print) -> dict:
    """`pauk import content/curricula/<name>.json`: one directory per
    unit, the unit's items linked into it (idempotent; items that do
    not exist yet are reported, import their items file first)."""
    space = data.get("space")
    dirs = linked = 0
    missing: list[str] = []
    for stage in data["stages"]:
        for unit in stage["units"]:
            dir_id = ensure_path(api, unit_path(data, stage["id"], unit["id"]))
            dirs += 1
            for key in unit["items"]:
                ref = key if "/" in key else f"{space}/{key}"
                try:
                    api.link_item_dir(dir_id, ref)
                    linked += 1
                except ApiError as e:
                    if e.code != "not_found":
                        raise
                    missing.append(ref)
    echo(f"curriculum {data['curriculum']}: {dirs} unit directories, {linked} item links")
    for ref in missing:
        echo(f"[yellow]item not found, not linked:[/yellow] {ref}")
    return {"dirs": dirs, "linked": linked, "missing": missing}
