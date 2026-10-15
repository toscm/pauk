"""Courses and the level map (docs/tutor.md 9.6): curriculum content,
stars from the memory model, unit goals, exam and generated units."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from conftest import REPO
from pauk.tutor import curriculum
from pauk.tutor import protocol as p
from pauk.tutor.fake import FakeApi
from pauk.tutor.host import create_app
from pauk.tutor.session import Session, SessionError

CONTENT = REPO / "content" / "curricula"
PACKAGED = REPO / "cli" / "pauk" / "data" / "curricula"


def _item_keys(space: str) -> set[str]:
    keys = set()
    for path in (REPO / "content").glob("items-*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        keys |= {i["key"] for i in data["items"] if i.get("space", data.get("space")) == space}
    return keys


@pytest.mark.parametrize("path", sorted(CONTENT.glob("*.json")), ids=lambda p: p.name)
def test_curriculum_content_is_consistent(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    assert json.loads((PACKAGED / path.name).read_text(encoding="utf-8")) == data, \
        f"copy {path.name} to cli/pauk/data/curricula/"
    keys = _item_keys(data["space"])
    seen: set[str] = set()
    for stage in data["stages"]:
        assert stage["title"]["en"] and stage["title"]["de"]
        ids = [u["id"] for u in stage["units"]]
        assert len(ids) == len(set(ids)), stage["id"]
        for unit in stage["units"]:
            assert re.fullmatch(r"u\d\d-[a-z0-9-]+", unit["id"]), unit["id"]
            assert unit["title"]["de"] and unit["can_do"]["de"], unit["id"]
            missing = [k for k in unit["items"] if k not in keys]
            assert not missing, f"{stage['id']}/{unit['id']}: no item {missing}"
            twice = seen & set(unit["items"])
            assert not twice, f"{stage['id']}/{unit['id']}: also in another unit: {twice}"
            seen |= set(unit["items"])


def test_bundled_courses_load():
    assert "italian" in curriculum.names()
    course = curriculum.load("italian")
    stage, unit = curriculum.find_unit(course, "a1", course["stages"][0]["units"][0]["id"])
    assert curriculum.unit_path(course, stage["id"], unit["id"]).startswith("italian/course/a1/")
    with pytest.raises(KeyError):
        curriculum.find_unit(course, "a1", "u99-nope")


def by(**counts) -> dict:
    return {str(k): counts.get(f"m{k}", 0) for k in range(6)}


@pytest.mark.parametrize("progress,generated,expected", [
    (None, False, 0),
    ({"items": 10, "by_mastery": by(m0=10), "due": 0}, False, 0),
    ({"items": 10, "by_mastery": by(m0=5, m3=5), "due": 0}, False, 1),
    ({"items": 10, "by_mastery": by(m1=2, m3=8), "due": 0}, False, 2),
    ({"items": 10, "by_mastery": by(m3=2, m4=6, m5=2), "due": 0}, False, 3),
    ({"items": 5, "by_mastery": by(m3=5), "due": 0}, True, 0),      # a generated unit needs 10 items
    ({"items": 12, "by_mastery": by(m3=12), "due": 0}, True, 2),
])
def test_stars(progress, generated, expected):
    assert curriculum.stars(progress, generated)["stars"] == expected


def test_refresh_when_much_is_due():
    s = curriculum.stars({"items": 10, "by_mastery": by(m3=10), "due": 4}, False)
    assert s["stars"] == 2 and s["refresh"] and s["share"] == 1.0
    assert not curriculum.stars({"items": 10, "by_mastery": by(m3=10), "due": 1}, False)["refresh"]


def _course_api() -> FakeApi:
    """A fake API with the Italian course imported (items created on the fly)."""
    api = FakeApi(seed=False)
    course = curriculum.load("italian")
    for stage in course["stages"]:
        for unit in stage["units"]:
            for key in unit["items"]:
                api._insert({"space": "it", "key": key, "kind": "word", "label_md": key, "gloss_md": key})
    result = curriculum.import_curriculum(api, course, echo=lambda *_: None)
    assert result["missing"] == []
    return api


def test_level_map_with_progress_and_recommendation():
    api = _course_api()
    course = curriculum.load("italian")
    first = course["stages"][0]["units"][0]
    for key in first["items"]:
        api.items[f"it/{key}"]["state"] = {"mastery": 3}
    levels = curriculum.level_map(api, "italian")
    a1 = levels["stages"][0]
    assert levels["imported"] and a1["units"][0]["stars"] == 2 and a1["passed"] == 1
    assert levels["recommended"] == {"stage": "a1", "unit": a1["units"][1]["id"]}
    assert a1["units"][1]["items"] == len(course["stages"][0]["units"][1]["items"])
    assert all(u["generated"] for u in levels["stages"][-1]["units"])

    assert curriculum.level_map(FakeApi(seed=False), "italian")["imported"] is False


def test_unit_session_goal_exam_and_generated_units(tmp_path):
    api = _course_api()
    session = Session(api, store_dir=tmp_path)
    client = TestClient(create_app(session))
    learner = {"X-Pauk-Key": session.keys["learner"]}
    base = f"/s/{session.sid}/api/learner"
    courses = client.get(f"{base}/courses", headers=learner).json()["courses"]
    assert [c["id"] for c in courses] == curriculum.names()

    r = client.post(f"{base}/start", json={"mode": "exam", "minutes": 15}, headers=learner)
    assert r.status_code == 400
    r = client.post(f"{base}/start", json={"mode": "exam", "minutes": 15,
                                           "unit": {"curriculum": "italian", "stage": "a1", "unit": "u99-nope"}}, headers=learner)
    assert r.status_code == 400
    course = curriculum.load("italian")
    unit = course["stages"][0]["units"][4]
    status = client.post(f"{base}/start", json={"mode": "exam", "minutes": 15,
                                                "unit": {"curriculum": "italian", "stage": "a1", "unit": unit["id"]}},
                         headers=learner).json()
    goal = status["goal"]
    assert goal["dirs"] == [f"italian/course/a1/{unit['id']}"]
    assert goal["unit"]["title"] == unit["title"]["en"] and goal["unit"]["can_do"] == unit["can_do"]["en"]
    assert goal["unit"]["planned_items"] == len(unit["items"]) and goal["unit"]["generated"] is False
    assert session.new_budget() == 999   # an exam tests unseen items without the new-item cap

    # a C2 unit without items: its directory is created and the teacher fills it directly
    other = Session(api, store_dir=tmp_path)
    c2 = course["stages"][-1]["units"][0]
    other.start(p.Start(mode="learn", unit=p.UnitRef(curriculum="italian", stage="c2", unit=c2["id"])))
    assert other.goal["unit"]["generated"] is True
    assert api.resolve_dir(f"italian/course/c2/{c2['id']}")
    with pytest.raises(SessionError):
        other.start(p.Start(mode="play"))
