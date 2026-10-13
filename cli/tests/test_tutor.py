"""The tutor session host: protocol rules, visibility of keys,
learner/teacher flows, and `pauk teach` against a live host. Uses the
in-memory FakeApi, so no PHP server is needed."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from pauk.client import ApiError
from pauk.tutor.fake import FakeApi
from pauk.tutor.host import create_app
from pauk.tutor.session import Session


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture()
def env(tmp_path):
    api = FakeApi()
    clock = Clock()
    session = Session(api, store_dir=tmp_path, clock=clock)
    client = TestClient(create_app(session))
    base = f"/s/{session.sid}/api"
    learner = {"X-Pauk-Key": session.keys["learner"]}
    teacher = {"Authorization": f"Bearer {session.keys['teacher']}"}
    observer = {"Authorization": f"Bearer {session.keys['observer']}"}

    def L(method, path, body=None, status=200):
        r = client.request(method, f"{base}/learner/{path}", json=body, headers=learner)
        assert r.status_code == status, r.text
        return r.json()

    def T(method, path, body=None, status=200, params=None):
        r = client.request(method, f"{base}/teacher/{path}", json=body, headers=teacher, params=params)
        assert r.status_code == status, r.text
        return r.json() if r.headers["content-type"].startswith("application/json") else r.text

    def O(method, path, body=None, status=200):
        r = client.request(method, f"{base}/observer/{path}", json=body, headers=observer)
        assert r.status_code == status, r.text
        return r.json()

    return type("Env", (), {"api": api, "session": session, "client": client, "L": L, "T": T, "O": O,
                            "clock": clock, "base": base})


MC = {"kind": "mc", "items": ["it/parlare"], "prompt_md": "Which word means **to speak**?",
      "options": [{"id": "a", "text_md": "parlare"}, {"id": "b", "text_md": "partire"}], "correct": ["a"]}


def test_keyed_exercise_flow_and_hidden_key(env):
    env.T("POST", "attach", {"agent": "test"})
    env.L("POST", "start", {"dirs": ["italian"], "mode": "mixed", "minutes": 15})
    asked = env.T("POST", "ask", {"exercise": MC})
    # the learner never sees the key before answering
    learner_events = env.L("GET", "state")["events"]
    shown = [e for e in learner_events if e["type"] == "exercise"][0]
    assert "correct" not in shown and shown["options"][0]["text_md"] == "parlare"
    teacher_view = [e for e in env.T("GET", "wait", params={"after": 0, "timeout": 0})["events"] if e["type"] == "exercise"][0]
    assert teacher_view["correct"] == ["a"]

    result = env.L("POST", "answer", {"exercise_id": asked["exercise_id"], "selected": ["a"]})
    assert result["correct"] is True
    events = env.T("GET", "wait", params={"after": 0, "timeout": 0})["events"]
    answered = [e for e in events if e["type"] == "answered"][0]
    assert answered["items"][0]["ref"] == "it/parlare" and answered["correct"] is True
    assert any(e["type"] == "level_change" for e in events)
    # recorded in the API with the session id and the raw response
    recorded = env.api.interactions[-1]
    assert recorded["session_id"] == env.session.sid and recorded["response"] == {"selected": ["a"]}
    # answering twice is refused
    env.L("POST", "answer", {"exercise_id": asked["exercise_id"], "selected": ["b"]}, status=409)


def test_open_exercise_must_be_graded_before_the_next_question(env):
    open_ex = {"kind": "open", "items": ["concepts/lasso"], "mode": "explain", "prompt_md": "Why is the Lasso sparse?",
               "reference_md": "The L1 penalty sets coefficients to zero."}
    ex = env.T("POST", "ask", {"exercise": open_ex})["exercise_id"]
    assert "reference_md" not in [e for e in env.L("GET", "state")["events"] if e["type"] == "exercise"][0]
    env.T("POST", "grade", {"exercise_id": ex, "outcomes": {"concepts/lasso": "good"}}, status=409)  # not answered
    env.L("POST", "answer", {"exercise_id": ex, "text": "Because of the L1 penalty."})
    err = env.T("POST", "ask", {"exercise": MC}, status=409)
    assert err["error"]["code"] == "grade_first"
    env.T("POST", "grade", {"exercise_id": ex, "outcomes": {"it/farfalla": "good"}}, status=400)  # wrong items
    env.T("POST", "grade", {"exercise_id": ex, "outcomes": {"concepts/lasso": "good"}, "feedback_md": "Exactly."})
    graded = [e for e in env.L("GET", "state")["events"] if e["type"] == "graded"][0]
    assert graded["correct"] is True and graded["reference_md"].startswith("The L1")
    env.T("POST", "ask", {"exercise": MC})


def test_drill_reports_once_when_done(env):
    drill = {"exercises": [
        {"kind": "text", "items": ["it/farfalla"], "prompt_md": "butterfly?", "accepted": ["farfalla"]},
        {"kind": "text", "items": ["it/ape"], "prompt_md": "bee?", "accepted": ["ape"]},
    ]}
    ids = env.T("POST", "drill", drill)["exercise_ids"]
    env.L("POST", "answer", {"exercise_id": ids[0], "text": "farfalla"})
    assert not [e for e in env.T("GET", "wait", params={"after": 0, "timeout": 0})["events"] if e["type"] == "drill_done"]
    env.L("POST", "dont-know", {"exercise_id": ids[1]})
    done = [e for e in env.T("GET", "wait", params={"after": 0, "timeout": 0})["events"] if e["type"] == "drill_done"]
    assert [r["correct"] for r in done[0]["results"]] == [True, False]
    env.T("POST", "drill", {"exercises": [MC, {**MC, "kind": "open"}]}, status=400)  # only keyed


def test_match_uses_opaque_tokens(env):
    ex = env.T("POST", "ask", {"exercise": {"kind": "match", "items": ["it/parlare"], "prompt_md": "Match",
                                            "pairs": [{"left_md": "io", "right_md": "parlo"}, {"left_md": "tu", "right_md": "parli"}]}})
    shown = [e for e in env.L("GET", "state")["events"] if e["type"] == "exercise"][-1]
    by_text = {r["right_md"]: r["token"] for r in shown["rights"]}
    result = env.L("POST", "answer", {"exercise_id": ex["exercise_id"], "matches": {"0": by_text["parlo"], "1": by_text["parli"]}})
    assert result["correct"] is True


def test_recall_reveal_then_self_grade(env):
    ex = env.T("POST", "ask", {"exercise": {"kind": "recall", "items": ["concepts/lasso"], "prompt_md": "Explain the Lasso",
                                            "reference_md": "L1-penalised regression."}})["exercise_id"]
    env.L("POST", "self-grade", {"exercise_id": ex, "correct": True}, status=400)  # not revealed
    assert env.L("POST", "reveal", {"exercise_id": ex})["reference_md"] == "L1-penalised regression."
    assert env.L("POST", "self-grade", {"exercise_id": ex, "correct": False})["correct"] is False
    assert env.api.interactions[-1]["grader"] == "self"


def test_unknown_items_and_validation(env):
    err = env.T("POST", "ask", {"exercise": {**MC, "items": ["it/nonexistent"]}}, status=400)
    assert err["error"]["code"] == "unknown_item"
    err = env.T("POST", "ask", {"exercise": {**MC, "correct": ["z"]}}, status=400)
    assert "correct" in err["error"]["message"]


def test_new_item_budget_is_enforced(env):
    env.api.settings_values["tutor.new_items_per_15min"] = 1
    env.session.settings = env.api.settings()
    env.T("POST", "introduce", {"ref": "it/farfalla"})
    err = env.T("POST", "introduce", {"ref": "it/ape"}, status=409)
    assert err["error"]["code"] == "new_item_cap"
    assert env.T("GET", "next", params={"dir": "italian"})["new"] == []


def test_add_item_follows_the_setting(env):
    item = {"space": "it", "kind": "word", "label_md": "vespa", "gloss_md": "wasp"}
    # propose (default): a proposal card, created on the learner's Add
    proposed = env.T("POST", "add-item", {"item": item})
    assert proposed["status"] == "proposed"
    assert "it/vespa" not in env.api.items
    env.L("POST", "proposal", {"proposal_id": proposed["proposal_id"], "action": "add"})
    assert env.api.items["it/vespa"]["attrs"]["origin"] == "teacher"
    # exact hit: the existing item comes back
    assert env.T("POST", "add-item", {"item": item})["status"] == "exists"
    # candidates are passed through to the teacher
    err = env.T("POST", "add-item", {"item": {**item, "label_md": "la vespa"}}, status=409)
    assert err["candidates"][0]["ref"] == "it/vespa"
    same = env.T("POST", "add-item", {"item": {**item, "label_md": "la vespa"}, "same_as": "it/vespa"})
    assert same["status"] == "alias"
    # free: created directly; off: refused
    env.api.settings_values["tutor.item_creation"] = "free"
    env.session.settings = env.api.settings()
    assert env.T("POST", "add-item", {"item": {"space": "it", "kind": "word", "label_md": "formica"}})["status"] == "created"
    env.api.settings_values["tutor.item_creation"] = "off"
    env.session.settings = env.api.settings()
    env.T("POST", "add-item", {"item": {"space": "it", "kind": "word", "label_md": "ragno"}}, status=403)


def test_on_request_needs_a_learner_message(env):
    env.api.settings_values["tutor.item_creation"] = "on_request"
    env.session.settings = env.api.settings()
    seq = env.L("POST", "message", {"text": "What is wasp in Italian? I want to learn it."})["seq"]
    created = env.T("POST", "add-item", {"item": {"space": "it", "kind": "word", "label_md": "vespa"}, "requested_seq": seq})
    assert created["status"] == "created"
    said = env.T("POST", "say", {"text_md": "Let me add a word."})["seq"]
    proposed = env.T("POST", "add-item", {"item": {"space": "it", "kind": "word", "label_md": "ragno"}, "requested_seq": said})
    assert proposed["status"] == "proposed"  # a teacher message is not a learner request


def test_merge_respects_setting(env):
    suggested = env.T("POST", "merge", {"into": "it/farfalla", "from": "it/ape", "reason": "test only"})
    assert suggested["status"] == "suggested" and not env.api.items["it/ape"]["archived"]


def test_reports_go_to_the_api_or_fall_back_locally(env, tmp_path):
    out = env.L("POST", "report", {"category": "bug", "text_md": "The match widget is cut off", "seq": 1})
    assert out["stored"] == "api"
    assert env.api.reports[0]["reporter"] == "learner" and env.api.reports[0]["session_uid"] == env.session.sid

    def missing(body):
        raise ApiError(404, "not_found", "Route not found")
    env.api.create_report = missing
    out = env.T("POST", "report", {"category": "teacher", "text_md": "No action to show two items side by side"})
    assert out["stored"] == "local"
    assert (tmp_path / "reports.jsonl").exists()


def test_observer_sees_audit_and_annotations_teacher_does_not(env):
    env.T("GET", "state")
    env.O("POST", "annotate", {"seq": 1, "text": "teacher read the state first", "tag": "ok"})
    observed = {e["type"] for e in env.O("GET", "state")["events"]}
    assert {"audit", "annotation"} <= observed
    taught = {e["type"] for e in env.T("GET", "wait", params={"after": 0, "timeout": 0})["events"]}
    assert not ({"audit", "annotation"} & taught)
    assert not ({"audit", "annotation"} & {e["type"] for e in env.L("GET", "state")["events"]})


def test_keys_are_role_specific(env):
    r = env.client.get(f"{env.base}/teacher/state", headers={"Authorization": f"Bearer {env.session.keys['learner']}"})
    assert r.status_code == 401
    r = env.client.get(f"{env.base}/learner/state", headers={"X-Pauk-Key": env.session.keys["teacher"]})
    assert r.status_code == 401


def test_time_warning_and_idle_end(env):
    env.L("POST", "start", {"dirs": [], "minutes": 5})
    env.clock.t += 181
    env.session.tick()
    assert [e for e in env.T("GET", "wait", params={"after": 0, "timeout": 0})["events"] if e["type"] == "time_warning"]
    env.clock.t += 601
    env.session.tick()
    assert env.session.ended
    env.L("POST", "message", {"text": "hello?"}, status=409)


def test_learner_end_gives_the_teacher_time_to_summarize(env):
    env.L("POST", "end")
    assert not env.session.ended
    env.T("POST", "end", {"summary_md": "Practised two words."})
    assert env.session.ended
    assert env.api.sessions[env.session.sid]["summary_md"] == "Practised two words."


def test_transcript_is_persisted(env, tmp_path):
    env.L("POST", "message", {"text": "ciao"})
    lines = (tmp_path / f"{env.session.sid}.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["type"] == "learner_message"


def test_pauk_teach_cli_against_a_live_host(tmp_path):
    session = Session(FakeApi(), store_dir=tmp_path)
    app = create_app(session)
    with __import__("socket").socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}/s/{session.sid}?key={session.keys['teacher']}"
    env = {"XDG_CACHE_HOME": str(tmp_path / "cache"), "PATH": __import__("os").environ.get("PATH", "")}

    def teach(*args, input_text=None):
        return subprocess.run([sys.executable, "-m", "pauk", "teach", "--session", url, *args],
                              capture_output=True, text=True, input=input_text, env={**__import__("os").environ, **env}, timeout=60)
    try:
        attached = teach("attach", "--agent", "pytest")
        assert attached.returncode == 0, attached.stdout + attached.stderr
        assert json.loads(attached.stdout)["protocol"] == 1
        assert "pauk teacher instructions" in teach("instructions").stdout
        asked = teach("ask", "-", input_text=json.dumps(MC))
        assert asked.returncode == 0, asked.stdout
        bad = teach("ask", json.dumps({**MC, "items": []}))
        assert bad.returncode == 1 and json.loads(bad.stdout)["error"]["code"] == "validation"
        waited = json.loads(teach("wait", "--timeout", "0").stdout)
        assert waited["events"]
        again = json.loads(teach("wait", "--timeout", "0").stdout)
        assert again["events"] == []   # the cursor continues where the last wait stopped
        assert json.loads(teach("help", "--json").stdout)["ask"]["properties"]["exercise"]

        learner_url = f"http://127.0.0.1:{port}/s/{session.sid}?key={session.keys['learner']}"

        def learn(*args):
            return subprocess.run([sys.executable, "-m", "pauk", "learn", "--session", learner_url, *args],
                                  capture_output=True, text=True, env={**__import__("os").environ, **env}, timeout=60)
        assert learn("start", "--dir", "italian", "--minutes", "10").returncode == 0
        exercise = [e for e in json.loads(learn("state").stdout)["events"] if e["type"] == "exercise"][0]
        assert "correct" not in exercise
        answered = learn("answer", exercise["exercise_id"], "--selected", "a")
        assert json.loads(answered.stdout)["correct"] is True, answered.stdout
        assert "pauk simulated learner instructions" in learn("instructions").stdout
    finally:
        server.should_exit = True


def test_payload_fields_never_override_the_envelope(env):
    env.L("POST", "message", {"text": "hi"})
    env.L("POST", "report", {"category": "idea", "text_md": "about the first message", "seq": 1})
    events = env.T("GET", "wait", params={"after": 0, "timeout": 0})["events"]
    assert [e["seq"] for e in events] == sorted({e["seq"] for e in events})
    report = [e for e in events if e["type"] == "report"][0]
    assert report["about_seq"] == 1 and report["seq"] > 1


def test_add_item_refuses_on_an_api_without_dry_run(tmp_path):
    api = FakeApi()
    api.version = "0.10.0"
    session = Session(api, store_dir=tmp_path)
    client = TestClient(create_app(session))
    r = client.post(f"/s/{session.sid}/api/teacher/add-item", json={"item": {"space": "it", "kind": "word", "label_md": "vespa"}},
                    headers={"Authorization": f"Bearer {session.keys['teacher']}"})
    assert r.status_code == 501 and r.json()["error"]["code"] == "api_too_old"
    assert "it/vespa" not in api.items


def test_route_activity(env):
    started = env.T("POST", "activity-start", {"type": "route", "spec": {"start": "muenchen", "goal": "nuernberg",
                                                                          "items": ["concepts/lasso"]}})
    aid = started["aid"]
    assert "Roads:" in started["text"]
    learner_view = [e for e in env.L("GET", "state")["events"] if e["type"] == "activity"][0]["view"]
    assert learner_view["graph"]["nodes"]["muenchen"]["name"] == "München"
    env.L("POST", "activity", {"aid": aid, "action": {"drive": "berlin"}}, status=400)   # no direct road
    env.L("POST", "activity", {"aid": aid, "action": {"drive": "ingolstadt"}})
    done = env.T("POST", "activity-act", {"aid": aid, "action": {"drive": "Nürnberg"}})
    assert done["state"]["done"] and done["state"]["km"] == 165
    events = env.T("GET", "wait", params={"after": 0, "timeout": 0})["events"]
    finished = [e for e in events if e["type"] == "activity_done"][0]
    assert finished["outcome"] == "good" and finished["optimal_km"] == 165
    assert env.api.interactions[-1]["source"] == "activity"
    assert env.T("GET", "activity", params={"aid": aid})["state"]["done"]
    env.L("POST", "activity", {"aid": aid, "action": {"undo": True}}, status=400)        # finished
    env.T("POST", "activity-start", {"type": "chess", "spec": {}}, status=400)


def test_parallel_answers_record_once(env):
    ex = env.T("POST", "ask", {"exercise": MC})["exercise_id"]
    statuses = []

    def submit():
        r = env.client.post(f"{env.base}/learner/answer", json={"exercise_id": ex, "selected": ["a"]},
                            headers={"X-Pauk-Key": env.session.keys["learner"]})
        statuses.append(r.status_code)
    threads = [threading.Thread(target=submit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses) == [200] + [409] * 7
    assert len(env.api.interactions) == 1


def test_report_response_never_leaks_exercise_keys(env):
    env.T("POST", "ask", {"exercise": {"kind": "text", "items": ["it/farfalla"], "prompt_md": "butterfly?",
                                       "accepted": ["SECRET-ANSWER"]}})
    response = env.client.post(f"{env.base}/learner/report", json={"category": "bug", "text_md": "x"},
                               headers={"X-Pauk-Key": env.session.keys["learner"]})
    assert response.status_code == 200
    assert "SECRET-ANSWER" not in response.text
    assert "SECRET-ANSWER" in json.dumps(env.api.reports[-1]["context"])   # the context still reaches the owner


def test_testing_an_unseen_item_spends_the_budget(env):
    env.api.settings_values["tutor.new_items_per_15min"] = 1
    env.session.settings = env.api.settings()
    env.T("POST", "ask", {"exercise": {**MC, "items": ["it/ape"]}})
    err = env.T("POST", "drill", {"exercises": [
        {"kind": "text", "items": ["it/farfalla"], "prompt_md": "butterfly?", "accepted": ["farfalla"]},
        {"kind": "text", "items": ["it/ape"], "prompt_md": "bee?", "accepted": ["ape"]}]}, status=409)
    assert err["error"]["code"] == "new_item_cap"


def test_sse_resumes_after_last_event_id(env):
    for text in ("one", "two", "three"):
        env.L("POST", "message", {"text": text})
    env.session.finish("system")
    with env.client.stream("GET", f"{env.base}/learner/events?k={env.session.keys['learner']}&after=0",
                           headers={"Last-Event-ID": "2"}) as r:
        body = r.read().decode()
    ids = [int(line[4:]) for line in body.splitlines() if line.startswith("id: ")]
    assert ids and min(ids) == 3


def test_pauk_teach_refuses_remote_hosts(tmp_path):
    out = subprocess.run([sys.executable, "-m", "pauk", "teach", "--session", "https://example.com/s/x?key=k", "state"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 1 and json.loads(out.stdout)["error"]["code"] == "not_local"


def test_simulate_refuses_the_real_server(tmp_path):
    persona = tmp_path / "p.md"
    persona.write_text("# Persona", encoding="utf-8")
    out = subprocess.run([sys.executable, "-m", "pauk", "--server", "https://pauk.aao756.de", "--token", "x",
                          "simulate", "--persona", str(persona)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 1 and "scratch API" in out.stdout


def test_simulation_marks_its_evidence(tmp_path):
    api = FakeApi()
    session = Session(api, store_dir=tmp_path, simulation=True)
    client = TestClient(create_app(session))
    client.post(f"/s/{session.sid}/api/teacher/introduce", json={"ref": "it/ape"},
                headers={"Authorization": f"Bearer {session.keys['teacher']}"})
    assert api.interactions[-1]["source"] == "simulation"


def test_after_the_learner_ends_the_teacher_can_only_wrap_up(env):
    env.L("POST", "end")
    err = env.T("POST", "ask", {"exercise": MC}, status=409)
    assert err["error"]["code"] == "learner_ended"
    env.T("POST", "say", {"text_md": "Ciao!"})
    env.T("POST", "end", {"summary_md": "Short session."})
