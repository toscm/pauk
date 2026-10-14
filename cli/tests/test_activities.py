"""Activity rules without a host (docs/tutor.md 14): map labelling and
the town scene, their role-filtered views, and the bundled content in
content/activities/ (every file loads, every ref is well formed and
names an item of the shipped item files, the packaged copy is equal)."""

from __future__ import annotations

import json
import re

import pytest

from conftest import REPO
from pauk.tutor import activities
from pauk.tutor.activities.common import REF, grade_name

CONTENT = REPO / "content" / "activities"
PACKAGED = REPO / "cli" / "pauk" / "data" / "activities"
SPECS = sorted(CONTENT.glob("*.json"))


def _items() -> set[str]:
    refs = set()
    for f in (REPO / "content").glob("items-*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        refs |= {f"{i.get('space', data['space'])}/{i['key']}" for i in data["items"]}
    return refs


# --- content -------------------------------------------------------------------

@pytest.mark.parametrize("file", SPECS, ids=[f.name for f in SPECS])
def test_activity_content_loads_and_refs_are_well_formed(file):
    data = json.loads(file.read_text(encoding="utf-8"))
    activity = activities.create(data["type"], {"ref": file.stem})
    refs = activity.refs()
    assert refs, "content without items records no evidence"
    assert all(REF.match(r) for r in refs), refs
    if data["type"] == "town":
        refs += [r for n in activity.npcs.values() for r in n["items"]]
    assert not set(refs) - _items(), "refs without an item in content/items-*.json"
    activity.describe("learner")
    json.dumps(activity.view("learner"))


def test_packaged_activity_content_equals_content_dir():
    sources = sorted(p.relative_to(CONTENT) for p in CONTENT.rglob("*.json"))
    copies = sorted(p.relative_to(PACKAGED) for p in PACKAGED.rglob("*.json"))
    assert sources == copies
    for rel in sources:
        assert json.loads((CONTENT / rel).read_text(encoding="utf-8")) == \
            json.loads((PACKAGED / rel).read_text(encoding="utf-8")), f"copy {rel} to cli/pauk/data/activities/"


def test_content_refs_and_overrides():
    town = activities.create("town", {"ref": "italian-town", "start": "bakery"})
    assert town.here == "bakery"
    with pytest.raises(ValueError, match="is a town activity"):
        activities.create("map_labels", {"ref": "italian-town"})
    with pytest.raises(ValueError, match="no activity content"):
        activities.create("town", {"ref": "atlantis"})
    with pytest.raises(ValueError, match="unknown activity type"):
        activities.create("chess", {})


# --- name grading ----------------------------------------------------------------

@pytest.mark.parametrize("answer,expected", [
    ("Nürnberg", "exact"), ("nuernberg", "exact"), ("NURNBERG", "exact"), ("Nuremberg", "exact"),
    ("Nurnbrg", "typo"), ("Nurnbreg", "wrong"), ("Nürnbergg", "typo"), ("Leipzig", "wrong"), ("", "wrong"),
])
def test_grade_name_folds_case_diacritics_and_umlauts(answer, expected):
    assert grade_name(answer, ["Nürnberg", "Nuremberg"], "de") == expected


def test_grade_name_ignores_articles():
    assert grade_name("il pane", ["pane"], "it") == "exact"
    assert grade_name("l'acqua", ["acqua"], "it") == "exact"
    assert grade_name("un caffe", ["caffè"], "it") == "exact"
    assert grade_name("il", ["il pane"], "it") == "wrong"
    assert grade_name("re", ["te"], "it") == "wrong"   # short names never pass as typos


# --- map labelling -----------------------------------------------------------------

CITIES = {"map": "germany", "input": "type", "places": [
    {"city": "muenchen", "item": "concepts/munchen", "accepted": ["Munich"]},
    {"city": "hamburg", "item": "concepts/hamburg"},
    {"city": "nuernberg", "item": "concepts/nurnberg"},
]}


def _numbers(m) -> dict:
    return {mk["name"]: n for n, mk in m.markers.items()}


def test_map_markers_are_numbered_north_to_south():
    m = activities.create("map_labels", CITIES)
    assert _numbers(m) == {"Hamburg": 1, "Nürnberg": 2, "München": 3}


def test_map_labels_undo_and_grading():
    m = activities.create("map_labels", CITIES)
    n = _numbers(m)
    assert m.act({"label": {"marker": n["Hamburg"], "name": "Hamburg"}}) == "marker 1 = Hamburg"
    m.act({"label": {"marker": n["Nürnberg"], "name": "Leipzig"}})
    assert "undone" in m.act({"undo": True})
    m.act({"label": {"marker": n["Nürnberg"], "name": "Nuernberg"}})
    m.act({"label": {"marker": n["München"], "name": "Munchn"}})
    with pytest.raises(ValueError, match="no marker 9"):
        m.act({"label": {"marker": 9, "name": "x"}})
    with pytest.raises(ValueError, match="actions"):
        m.act({"drive": "berlin"})
    assert m.act({"finish": True}) == "finished: 3 of 3 correct"
    result = m.result()
    assert result["items"] == {"concepts/hamburg": "good", "concepts/nurnberg": "good", "concepts/munchen": "hard"}
    assert result["outcome"] == "good" and result["mode"] == "recall"
    with pytest.raises(ValueError, match="finished"):
        m.act({"undo": True})


def test_map_pick_mode_only_accepts_listed_names_and_unlabelled_fail():
    m = activities.create("map_labels", {**CITIES, "input": "pick", "distractors": ["Kassel"]})
    assert m.view("learner")["names"] == ["Hamburg", "Kassel", "München", "Nürnberg"]
    with pytest.raises(ValueError, match="not one of the names"):
        m.act({"label": {"marker": 1, "name": "Paris"}})
    m.act({"label": {"marker": 1, "name": "hamburg"}})
    assert m.labels[1] == "Hamburg"
    m.act({"give_up": True})
    assert m.result()["items"]["concepts/munchen"] == "fail" and m.result()["detail"]["gave_up"]


def test_map_learner_view_has_no_key():
    m = activities.create("map_labels", {"ref": "germany-states"})
    view = m.view("learner")
    markers = json.dumps(view["markers"], ensure_ascii=False) + json.dumps(view["map"], ensure_ascii=False)
    for secret in ("Bayern", "bayern", "concepts/", "accepted", '"id"'):
        assert secret not in markers
    text = m.describe("learner")
    assert "concepts/" not in text and "key:" not in text and "Names: Baden-Württemberg, Bayern" in text
    assert "[key: Schleswig-Holstein, concepts/schleswig-holstein]" in m.describe("teacher")
    teacher = m.view("teacher")
    assert teacher["markers"][0]["name"] == "Schleswig-Holstein" and teacher["map"]["regions"][0]["name"] == "Bayern"
    m.act({"finish": True})
    assert m.view("learner")["markers"][0]["name"] == "Schleswig-Holstein"   # revealed once graded


def test_map_spec_validation():
    for spec, message in [({"places": []}, "1-40 places"), ({"places": [{"region": "atlantis"}]}, "unknown region"),
                          ({"places": [{"city": "paris"}]}, "unknown city"), ({"places": [{"x": 1}]}, "needs"),
                          ({"places": [{"city": "hof", "item": "Hof"}]}, "not an item ref"),
                          ({"input": "draw", "places": [{"city": "hof"}]}, "input")]:
        with pytest.raises(ValueError, match=message):
            activities.create("map_labels", spec)


# --- town -------------------------------------------------------------------------------

TOWN = {"title": "Test", "language": "it", "start": "square",
        "places": [{"id": "square", "name": "la piazza", "at": [0, 0]}, {"id": "bakery", "name": "la panetteria", "at": [1, 0]},
                   {"id": "station", "name": "la stazione", "at": [2, 0]}],
        "streets": [["square", "bakery"], ["bakery", "station"]],
        "objects": [{"id": "bread", "place": "bakery", "icon": "🍞", "hint": "bread", "accepted": ["pane"], "item": "it/pane"},
                    {"id": "train", "place": "station", "icon": "🚆", "hint": "train", "accepted": ["treno"], "item": "it/treno"}],
        "npcs": [{"id": "baker", "name": "Giulia", "place": "bakery", "persona": "SECRET-PERSONA",
                  "items": ["it/grazie"], "greeting": "Buongiorno!",
                  "goal": {"task_md": "Order bread.", "success": "SECRET-SUCCESS", "items": ["it/vorrei", "it/pane"],
                           "max_turns": 2}}]}


def test_town_walking_and_inspecting():
    t = activities.create("town", TOWN)
    with pytest.raises(ValueError, match="go there first"):
        t.act({"inspect": "bread"})
    assert t.act({"go_to": "train"}) == "walked to la stazione via la panetteria"
    assert t.trail == ["square", "bakery", "station"] and t.talk == []   # passing by is no visit
    t.act({"go_to": "la panetteria"})
    assert t.talk == [{"npc": "baker", "from": "npc", "text": "Buongiorno!"}]
    assert t.act({"inspect": "bread"}) == "inspecting 🍞 bread: what is it called?"
    assert t.act({"answer": "il pane"}) == "✓ pane"
    assert t.evidence() == [{"mode": "recall", "items": {"it/pane": "good"},
                             "detail": {"object": "bread", "answer": "il pane", "match": "exact"}}]
    assert t.act({"inspect": "bread"}) == "🍞 bread: pane"   # named once, no new question
    assert t.evidence() == []
    with pytest.raises(ValueError, match="inspect an object first"):
        t.act({"answer": "pane"})
    t.act({"go_to": "station"})
    t.act({"inspect": "train"})
    assert t.act({"dont_know": True}) == "✗ it is treno"
    assert t.evidence()[0]["items"] == {"it/treno": "fail"}


def test_town_greeting_only_on_arrival():
    t = activities.create("town", TOWN)
    assert t.talk == []
    t.act({"go_to": "bakery"})
    t.act({"go_to": "square"})
    t.act({"go_to": "bakery"})
    assert [x["text"] for x in t.talk] == ["Buongiorno!"]


def test_town_conversation_roles_turns_and_grading():
    t = activities.create("town", TOWN)
    with pytest.raises(ValueError, match="go there first"):
        t.act({"say": {"npc": "baker", "text": "Ciao"}})
    t.act({"go_to": "bakery"})
    with pytest.raises(ValueError, match="only the learner"):
        t.act({"say": {"npc": "baker", "text": "Ciao"}}, "teacher")
    with pytest.raises(ValueError, match="from the teacher"):
        t.act({"npc": "baker", "say": "Prego"}, "learner")
    with pytest.raises(ValueError, match="graded by the teacher"):
        t.act({"grade": {"npc": "baker", "outcomes": {}}}, "learner")
    with pytest.raises(ValueError, match="has not talked"):
        t.act({"grade": {"npc": "baker", "outcomes": {"it/vorrei": "good", "it/pane": "good"}}}, "teacher")
    t.act({"say": {"npc": "baker", "text": "Vorrei pane"}})
    t.act({"npc": "baker", "say": "Quanto?"}, "teacher")
    t.act({"say": {"npc": "Giulia", "text": "Uno, per favore"}})
    with pytest.raises(ValueError, match="reached its length"):
        t.act({"say": {"npc": "baker", "text": "Grazie"}})
    assert "Waiting for your NPC line: baker" in t.describe("teacher")
    with pytest.raises(ValueError, match="cover exactly"):
        t.act({"grade": {"npc": "baker", "outcomes": {"it/pane": "good"}}}, "teacher")
    t.act({"finish": True})
    # a goal can still be graded after the learner left
    summary = t.act({"grade": {"npc": "baker", "outcomes": {"it/vorrei": "good", "it/pane": "hard"},
                               "feedback": "Bene!"}}, "teacher")
    assert summary == "goal with Giulia: reached"
    evidence = t.evidence()[0]
    assert evidence["mode"] == "produce" and evidence["items"] == {"it/vorrei": "good", "it/pane": "hard"}
    assert len(evidence["detail"]["conversation"]) == 4
    with pytest.raises(ValueError, match="already graded"):
        t.act({"grade": {"npc": "baker", "outcomes": {"it/vorrei": "good", "it/pane": "good"}}}, "teacher")
    assert t.result()["items"] == {} and t.result()["outcome"] == "good"


def test_town_learner_view_has_no_key():
    t = activities.create("town", TOWN)
    t.act({"go_to": "bakery"})
    learner = json.dumps(t.view("learner"), ensure_ascii=False) + t.describe("learner")
    for secret in (r"SECRET-PERSONA", r"SECRET-SUCCESS", r"accepted", r"\bpane\b", r"it/"):
        assert not re.search(secret, learner), secret
    teacher = json.dumps(t.view("teacher"), ensure_ascii=False) + t.describe("teacher")
    for secret in (r"SECRET-PERSONA", r"SECRET-SUCCESS", r"\bpane\b", r"it/vorrei"):
        assert re.search(secret, teacher), secret
    t.act({"inspect": "bread"})
    t.act({"answer": "pan"})
    assert t.view("learner")["objects"][0]["name"] == "pane"   # revealed after answering


def test_town_describe_is_enough_to_act():
    t = activities.create("town", TOWN)
    text = t.describe("learner")
    assert "You are at la piazza (square)" in text and "Streets lead to: la panetteria" in text
    assert '{"go_to"' in text
    t.act({"go_to": "bakery"})
    text = t.describe("learner")
    assert "🍞 bread [bread]" in text and "Person here: 🙂 Giulia [baker]; task: Order bread. (0/2 turns)" in text
    assert "Giulia: Buongiorno!" in text


def test_town_spec_validation():
    for spec, message in [({"places": []}, "needs places"),
                          ({**TOWN, "streets": [["square", "moon"]]}, "two place ids"),
                          ({**TOWN, "objects": [{"id": "x", "place": "square"}]}, "accepted"),
                          ({**TOWN, "objects": [{"id": "Bread", "place": "square", "accepted": ["pane"]}]}, "slugs"),
                          ({**TOWN, "start": "moon"}, "start"),
                          ({**TOWN, "npcs": [{"id": "x", "place": "square", "goal": {"task_md": "t"}}]}, "goal needs")]:
        with pytest.raises(ValueError, match=message):
            activities.create("town", spec)
