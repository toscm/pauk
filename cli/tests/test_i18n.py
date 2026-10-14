"""The browser UI's language (issue 0017): message catalogues in
cli/pauk/tutor/static/i18n/, message ids used by the JS modules and by
the activity summaries, the learner's tutor.language reaching the
browser, and translated content texts (task_md, hint, prompt_md)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from conftest import REPO
from pauk.tutor import activities
from pauk.tutor.activities.common import Msg, english, localized
from pauk.tutor.activities.route import COMPASS
from pauk.tutor.fake import FakeApi
from pauk.tutor.host import create_app
from pauk.tutor.session import Session

TUTOR = REPO / "cli" / "pauk" / "tutor"
STATIC = TUTOR / "static"
ENTRY = re.compile(r"^\s*'([^']+)':\s*'(.*)',\s*$")
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _catalogue(path) -> dict[str, str]:
    """`'id': 'text',` lines of an i18n/<lang>.js file."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = ENTRY.match(line)
        if m:
            assert m.group(1) not in out, f"{path.name}: {m.group(1)} twice"
            out[m.group(1)] = m.group(2)
    return out


CATALOGUES = {p.stem: _catalogue(p) for p in sorted((STATIC / "i18n").glob("*.js"))}
EN = CATALOGUES["en"]


def _js_ids() -> set[str]:
    ids = set()
    for path in STATIC.glob("*.js"):
        ids |= set(re.findall(r"\bt\('([^']+)'", path.read_text(encoding="utf-8")))
    ids |= set(re.findall(r'data-i18n[a-z-]*="([^"]+)"', (STATIC / "index.html").read_text(encoding="utf-8")))
    return ids


def _python_messages() -> dict[str, str]:
    """Msg ids and English templates in the activity modules and the session."""
    out = {}
    for path in [*(TUTOR / "activities").glob("*.py"), TUTOR / "session.py"]:
        for msg_id, template in re.findall(r'Msg\(\s*"([^"]+)",\s*"([^"]*)"', path.read_text(encoding="utf-8")):
            out[msg_id] = template
    return out


def test_catalogues_parse_and_english_is_there():
    assert {"en", "de"} <= set(CATALOGUES)
    assert len(EN) > 200   # every line parsed
    raw = (STATIC / "i18n" / "en.js").read_text(encoding="utf-8")
    assert raw.count("':") == len(EN), "an entry the test cannot parse (one 'id': 'text', per line)"


@pytest.mark.parametrize("lang", sorted(CATALOGUES))
def test_every_catalogue_is_complete(lang):
    catalogue = CATALOGUES[lang]
    assert set(catalogue) == set(EN), (f"missing in {lang}: {sorted(set(EN) - set(catalogue))}; "
                                       f"unknown: {sorted(set(catalogue) - set(EN))}")
    for key, text in catalogue.items():
        assert set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(EN[key])), f"{lang} {key}: placeholders"
        assert text.strip(), f"{lang} {key} is empty"


def test_every_id_used_in_the_browser_exists():
    used = _js_ids()
    assert len(used) > 150
    assert not used - set(EN), sorted(used - set(EN))


def test_every_activity_message_exists_and_matches_its_english_template():
    messages = _python_messages()
    assert len(messages) >= 20
    for msg_id, template in messages.items():
        assert msg_id in EN, f"{msg_id} is not in i18n/en.js"
        assert EN[msg_id] == template, f"{msg_id}: en.js and the Python template differ"
    # route directions come from the host (COMPASS) and are translated in activity.js
    assert {f"route.dir.{d}" for d in COMPASS} <= _js_ids()


def test_activity_summaries_carry_message_ids():
    town = activities.create("town", {"ref": "italian-town"})
    walked = town.act({"go_to": "bakery"})
    assert walked.startswith("walked to la panetteria") and walked.message()["id"].startswith("town.walked")
    inspected = town.act({"inspect": "bread"})
    assert inspected == "inspecting 🍞 bread: what is it called?"
    assert inspected.message() == {"id": "town.inspecting", "params": {"icon": "🍞", "hint": {"en": "bread", "de": "Brot"}}}
    assert town.act({"dont_know": True}).message() == {"id": "town.answer_unknown", "params": {"name": "pane"}}
    msg = Msg("map.labelled", "marker {n} = {name}", n=3, name="Leipzig")
    assert msg == "marker 3 = Leipzig" and json.dumps({"summary": msg}) == '{"summary": "marker 3 = Leipzig"}'


# --- the setting reaches the browser ------------------------------------------------

@pytest.fixture()
def host(tmp_path):
    session = Session(FakeApi(), store_dir=tmp_path)
    client = TestClient(create_app(session))
    base = f"/s/{session.sid}/api"
    learner = {"X-Pauk-Key": session.keys["learner"]}

    def L(method, path, body=None):
        r = client.request(method, f"{base}/learner/{path}", json=body, headers=learner)
        assert r.status_code == 200, r.text
        return r.json()

    teacher = {"Authorization": f"Bearer {session.keys['teacher']}"}

    def T(path, body):
        r = client.post(f"{base}/teacher/{path}", json=body, headers=teacher)
        assert r.status_code == 200, r.text
        return r.json()

    return type("Host", (), {"L": L, "T": T, "session": session})


def test_the_language_setting_reaches_the_browser(host):
    """The browser picks its catalogue from tutor.language in the state
    it loads, the status it polls and the settings_changed event."""
    assert host.L("GET", "state")["settings"]["tutor.language"] == "en"
    host.L("PATCH", "settings", {"tutor.language": "de"})
    assert host.L("GET", "status")["settings"]["tutor.language"] == "de"
    changed = [e for e in host.L("GET", "state")["events"] if e["type"] == "settings_changed"]
    assert changed and changed[-1]["settings"]["tutor.language"] == "de"
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "setLanguage(state.settings?.['tutor.language'])" in app
    assert "case 'settings_changed':" in app and "useLanguage(status.settings)" in app


def test_learner_activity_updates_carry_the_message(host):
    aid = host.T("activity-start", {"type": "town", "spec": {"ref": "italian-town"}})["aid"]
    acted = host.L("POST", "activity", {"aid": aid, "action": {"go_to": "bakery"}})
    assert acted["summary_msg"]["id"].startswith("town.walked")
    update = [e for e in host.L("GET", "state")["events"] if e["type"] == "activity_update"][-1]
    assert update["summary_msg"] == acted["summary_msg"]
    ended = host.T("activity-end", {"aid": aid})
    assert ended["ok"]


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="needs node to run the browser module")
def test_i18n_module_selects_the_catalogue(tmp_path):
    """i18n.js in node with a stub document: the tag's primary subtag
    picks the catalogue, unknown languages fall back to English."""
    script = tmp_path / "check.mjs"
    script.write_text("""
globalThis.document = {documentElement: {}, querySelectorAll: () => []};
const i18n = await import(process.argv[2]);
const out = {};
out.en = i18n.t('app.send');
await i18n.setLanguage('de-AT');
out.lang = i18n.language();
out.de = i18n.t('town.question', {thing: {en: 'bread', de: 'Brot'}, language: 'Italienisch'});
out.msg = i18n.message({id: 'town.walked', params: {place: 'la piazza'}}, 'walked to la piazza');
out.fallback = i18n.message({id: 'no.such.id', params: {}}, 'fallback');
out.local = i18n.local({en: 'Order bread.', de: 'Bestelle Brot.'});
out.plain = i18n.local('plain');
await i18n.setLanguage('xx');
out.unknown = [i18n.language(), i18n.t('app.send')];
console.log(JSON.stringify(out));
""", encoding="utf-8")
    url = (STATIC / "i18n.js").as_uri()
    result = subprocess.run([NODE, str(script), url], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out == {"en": "Send", "lang": "de", "de": "Wie heißt das (Brot) auf Italienisch?",
                   "msg": "zu la piazza gegangen", "fallback": "fallback", "local": "Bestelle Brot.",
                   "plain": "plain", "unknown": ["en", "Send"]}


# --- translated content texts ----------------------------------------------------------

def test_localized_texts_accept_strings_and_translations():
    assert localized("Order bread.", "x") == "Order bread."
    assert localized({"en": "Order bread.", "de": "Bestelle Brot."}, "x")["de"] == "Bestelle Brot."
    assert localized(None, "x") is None
    for bad in ({}, {"en": ""}, {"EN!": "x"}, {"en": 3}, ["en"]):
        with pytest.raises(ValueError, match="translations"):
            localized(bad, "task_md")
    assert english({"de": "Brot", "en": "bread"}) == "bread" and english({"de": "Brot"}) == "Brot"


@pytest.mark.parametrize("name", ["italian-town", "germany-states", "germany-cities"])
def test_bundled_content_has_german(name):
    data = json.loads((REPO / "content" / "activities" / f"{name}.json").read_text(encoding="utf-8"))
    spec = data["spec"]
    texts = [spec["prompt_md"]]
    texts += [o["hint"] for o in spec.get("objects", [])]
    texts += [n["goal"]["task_md"] for n in spec.get("npcs", []) if n.get("goal")]
    for text in texts:
        assert isinstance(text, dict) and text.get("en") and text.get("de"), text


def test_town_task_translations_reach_the_learner_and_agents_read_english():
    town = activities.create("town", {"ref": "italian-town", "start": "bakery"})
    view = town.view("learner")
    baker = next(n for n in view["npcs"] if n["id"] == "baker")
    assert baker["goal"]["task_md"]["de"].startswith("Bestelle")
    assert isinstance(view["prompt_md"], dict) and next(o for o in view["objects"] if o["id"] == "bread")["hint"]["de"] == "Brot"
    text = town.describe("teacher")
    assert "task: Order **two croissants" in text and "Bestelle" not in text and "🍞 bread [bread]" in text
    # a hint in any language finds the object
    assert town.act({"inspect": "Brot"}).startswith("inspecting 🍞 bread")
    # plain strings still work
    plain = activities.create("town", {"ref": "italian-town", "start": "bakery", "prompt_md": "Walk."})
    assert plain.view("learner")["prompt_md"] == "Walk."
    with pytest.raises(ValueError, match="translations"):
        activities.create("town", {"ref": "italian-town", "prompt_md": {"en": ""}})
