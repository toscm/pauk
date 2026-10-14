"""`pauk teach` and `pauk observe`: the command-line clients the
teacher and observer agents use (docs/tutor.md 9.2, 15.1).

Every command prints JSON on stdout; errors print a JSON error and
exit with status 1. The session comes from `--session URL` (which may
carry `?key=...`) or PAUK_SESSION + PAUK_TEACHER_KEY /
PAUK_OBSERVER_KEY. `wait` without `--after` continues where the last
`wait` of this session stopped.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import parse_qs, urlparse

import httpx
import typer

from pauk.tutor import protocol as p

teach_app = typer.Typer(add_completion=False, rich_markup_mode=None,
                        help="Teacher commands for a running pauk tutor session (JSON in, JSON out).")
observe_app = typer.Typer(add_completion=False, rich_markup_mode=None,
                          help="Observer commands for a running pauk tutor session.")

_ctx: dict[str, Any] = {}


def _session(role: str) -> tuple[str, str]:
    url = _ctx.get("session") or os.environ.get("PAUK_SESSION")
    if not url:
        _fail("no_session", "No session: pass --session URL or set PAUK_SESSION")
    parsed = urlparse(url)
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        _fail("not_local", "pauk teach only talks to a local session host (127.0.0.1)")
    key = (parse_qs(parsed.query).get("key") or [None])[0] or os.environ.get(f"PAUK_{role.upper()}_KEY")
    if not key:
        _fail("no_key", f"No {role} key: append ?key=... to the session URL or set the environment variable")
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    return base, key


def _fail(code: str, message: str) -> None:
    print(json.dumps({"error": {"code": code, "message": message}}))
    raise typer.Exit(1)


def _request(role: str, method: str, path: str, *, json_body: Any = None, params: dict | None = None,
             timeout: float = 30) -> Any:
    base, key = _session(role)
    try:
        response = httpx.request(method, f"{base}/api/{role}/{path}", json=json_body,
                                 params={k: v for k, v in (params or {}).items() if v is not None},
                                 headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
    except httpx.TransportError as e:
        _fail("unreachable", f"Session host not reachable ({e.__class__.__name__}); has the session ended?")
    if response.headers.get("content-type", "").startswith("text/plain"):
        if response.status_code >= 400:
            _fail("http_" + str(response.status_code), response.text)
        return response.text
    try:
        data = response.json()
    except ValueError:
        _fail("http_" + str(response.status_code), response.text[:500])
    if response.status_code >= 400:
        if isinstance(data, dict) and "error" not in data:
            data = {"error": {"code": "http_" + str(response.status_code), "message": str(data.get("detail", data))}}
        print(json.dumps(data, ensure_ascii=False, indent=1))
        raise typer.Exit(1)
    return data


def _out(data: Any) -> None:
    if isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=1))


def _json_arg(value: str) -> Any:
    """Literal JSON, `-` for stdin, or `@file`."""
    if value == "-":
        value = sys.stdin.read()
    elif value.startswith("@"):
        value = Path(value[1:]).read_text(encoding="utf-8")
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        _fail("bad_json", f"Invalid JSON argument: {e}")


def _text_arg(value: str) -> str:
    return sys.stdin.read() if value == "-" else value


def _cursor_file(role: str) -> Path:
    base, _ = _session(role)
    name = base.rstrip("/").split("/")[-1]
    root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "pauk"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{role}-{name}.seq"


def _wait(role: str, after: Optional[int], timeout: float) -> None:
    cursor = _cursor_file(role)
    if after is None:
        after = int(cursor.read_text()) if cursor.exists() else 0
    data = _request(role, "GET", "wait", params={"after": after, "timeout": timeout}, timeout=timeout + 15)
    cursor.write_text(str(data["last_seq"]))
    _out(data)


@teach_app.callback()
def teach_main(session: Optional[str] = typer.Option(None, "--session", help="Session URL (may include ?key=...)")) -> None:
    _ctx["session"] = session


@teach_app.command()
def attach(agent: Optional[str] = typer.Option(None, "--agent", help="Your name, e.g. claude-code"),
           takeover: bool = typer.Option(False, "--takeover")) -> None:
    """Attach as the teacher (checks the protocol version)."""
    data = _request("teacher", "POST", "attach", json_body={"agent": agent, "takeover": takeover})
    if data.get("protocol") != p.PROTOCOL:
        _fail("protocol_mismatch", f"Host speaks protocol {data.get('protocol')}, this pauk {p.PROTOCOL}: upgrade pauk")
    _out(data)


@teach_app.command()
def instructions() -> None:
    """Print the teacher instructions."""
    _out(_request("teacher", "GET", "instructions"))


@teach_app.command("help")
def help_cmd(as_json: bool = typer.Option(False, "--json", help="JSON schemas of all actions")) -> None:
    """List the actions (with --json: their JSON schemas)."""
    _out(p.schemas() if as_json else sorted(p.TEACHER_ACTIONS))


@teach_app.command()
def state() -> None:
    """Goal, settings, open exercises, transcript tail, touched items."""
    _out(_request("teacher", "GET", "state"))


@teach_app.command()
def wait(after: Optional[int] = typer.Option(None, "--after"), timeout: float = typer.Option(90, "--timeout")) -> None:
    """Block until learner events arrive (max --timeout seconds)."""
    _wait("teacher", after, timeout)


@teach_app.command()
def profile(dir: Optional[str] = typer.Option(None, "--dir")) -> None:
    """Profile summary of a subject (or everything)."""
    _out(_request("teacher", "GET", "profile", params={"dir": dir}))


@teach_app.command("next")
def next_cmd(dir: Optional[str] = typer.Option(None, "--dir"), n: int = typer.Option(10, "--n")) -> None:
    """What to practise next: review and new items."""
    _out(_request("teacher", "GET", "next", params={"dir": dir, "n": n}))


@teach_app.command()
def items(q: Optional[str] = typer.Option(None, "--q"), dir: Optional[str] = typer.Option(None, "--dir"),
          space: Optional[str] = typer.Option(None, "--space"), kind: Optional[str] = typer.Option(None, "--kind")) -> None:
    """Search the profile."""
    _out(_request("teacher", "GET", "items", params={"q": q, "dir": dir, "space": space, "kind": kind}))


@teach_app.command()
def item(ref: str) -> None:
    """One item with state, links, cards and history."""
    _out(_request("teacher", "GET", "item", params={"ref": ref}))


def _act(name: str, body: dict) -> None:
    _out(_request("teacher", "POST", name, json_body=body))


@teach_app.command()
def say(text: str = typer.Argument(..., help="Markdown, or - for stdin")) -> None:
    """Send a chat message."""
    _act("say", {"text_md": _text_arg(text)})


@teach_app.command()
def introduce(ref: str, text: Optional[str] = typer.Option(None, "--text")) -> None:
    """Show an item card and record the introduction."""
    _act("introduce", {"ref": ref, "text_md": text})


@teach_app.command()
def ask(exercise: str = typer.Argument(..., help="Exercise JSON, - for stdin, @file")) -> None:
    """Ask one exercise."""
    _act("ask", {"exercise": _json_arg(exercise)})


@teach_app.command()
def drill(exercises: str = typer.Argument(..., help='{"exercises": [...]} or a JSON list; - for stdin')) -> None:
    """Ask 2-20 keyed exercises back to back."""
    data = _json_arg(exercises)
    _act("drill", data if isinstance(data, dict) else {"exercises": data})


@teach_app.command()
def grade(exercise_id: str, outcomes: str = typer.Option(..., "--outcomes", help='JSON: {"ref": "good", ...}'),
          feedback: Optional[str] = typer.Option(None, "--feedback"),
          notes: Optional[str] = typer.Option(None, "--notes", help='JSON: {"ref": "note"}')) -> None:
    """Grade an answered open exercise."""
    _act("grade", {"exercise_id": exercise_id, "outcomes": _json_arg(outcomes), "feedback_md": feedback,
                   "notes": _json_arg(notes) if notes else {}})


@teach_app.command()
def override(exercise_id: str, outcomes: str = typer.Option(..., "--outcomes"),
             reason: str = typer.Option(..., "--reason")) -> None:
    """Correct an automatic grade (once per exercise)."""
    _act("override", {"exercise_id": exercise_id, "outcomes": _json_arg(outcomes), "reason": reason})


@teach_app.command()
def hint(exercise_id: str, text: str) -> None:
    """Give a hint for an unanswered exercise."""
    _act("hint", {"exercise_id": exercise_id, "text_md": _text_arg(text)})


@teach_app.command()
def note(ref: str, text: str) -> None:
    """Set your memo about this learner and item."""
    _act("note", {"ref": ref, "text": _text_arg(text)})


@teach_app.command()
def focus(ref: str) -> None:
    """Flag an item as focus (only when the learner asks)."""
    _act("focus", {"ref": ref})


@teach_app.command()
def suspend(ref: str) -> None:
    """Suspend an item (only when the learner asks)."""
    _act("suspend", {"ref": ref})


@teach_app.command()
def link(ref: str, dir: str) -> None:
    """Add an item to a subject directory."""
    _act("link", {"ref": ref, "dir": dir})


@teach_app.command()
def merge(into: str, from_ref: str = typer.Argument(..., metavar="FROM"), reason: str = typer.Option(..., "--reason")) -> None:
    """FROM is the same thing as INTO."""
    _act("merge", {"into": into, "from": from_ref, "reason": reason})


@teach_app.command("add-item")
def add_item(item_json: str = typer.Argument(..., metavar="JSON"),
             same_as: Optional[str] = typer.Option(None, "--same-as"),
             distinct_from: List[str] = typer.Option([], "--distinct-from"),
             reason: Optional[str] = typer.Option(None, "--reason"),
             requested_seq: Optional[int] = typer.Option(None, "--requested-seq")) -> None:
    """Add a missing item (duplicate protocol and settings apply)."""
    _act("add-item", {"item": _json_arg(item_json), "same_as": same_as, "distinct_from": distinct_from,
                      "reason": reason, "requested_seq": requested_seq})


@teach_app.command()
def report(category: str, text: str, seq: Optional[int] = typer.Option(None, "--seq")) -> None:
    """Report a problem (bug, content, teacher, ux, idea)."""
    _act("report", {"category": category, "text_md": _text_arg(text), "seq": seq})


@teach_app.command()
def end(summary: str = typer.Argument(..., help="Markdown summary, or - for stdin")) -> None:
    """Close the session with a summary."""
    _act("end", {"summary_md": _text_arg(summary)})


activity_app = typer.Typer(add_completion=False, rich_markup_mode=None,
                           help="Activities: an autobahn route, map labelling, a town scene.")
teach_app.add_typer(activity_app, name="activity")


@activity_app.command("start")
def activity_start(type_: str = typer.Argument(..., metavar="TYPE", help="route, map_labels or town"),
                   spec: str = typer.Argument(..., metavar="SPEC_REF",
                                              help='bundled content name (e.g. italian-town, germany-states) '
                                                   'or JSON, e.g. {"start": "muenchen", "goal": "berlin"}')) -> None:
    """Start an activity; returns its aid and a text description."""
    data = {"ref": spec} if re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", spec) else _json_arg(spec)
    _act("activity-start", {"type": type_, "spec": data})


@activity_app.command("act")
def activity_act(aid: str, action: str = typer.Argument(..., help='JSON, e.g. {"drive": "nuernberg"}')) -> None:
    """Act in an activity (e.g. on the learner's spoken instruction)."""
    _act("activity-act", {"aid": aid, "action": _json_arg(action)})


@activity_app.command("observe")
def activity_observe(aid: str) -> None:
    """Current state and text description."""
    _out(_request("teacher", "GET", "activity", params={"aid": aid}))


@activity_app.command("end")
def activity_end(aid: str) -> None:
    """End an activity (counts as given up; a map records only labelled markers); stops ungraded-goal reminders."""
    _act("activity-end", {"aid": aid})


# --- observer --------------------------------------------------------------------

@observe_app.callback()
def observe_main(session: Optional[str] = typer.Option(None, "--session", help="Session URL (may include ?key=...)")) -> None:
    _ctx["session"] = session


@observe_app.command("instructions")
def observe_instructions() -> None:
    """Print the observer instructions."""
    from importlib import resources

    print(resources.files("pauk.tutor").joinpath("observer.md").read_text(encoding="utf-8"))


@observe_app.command("state")
def observe_state() -> None:
    """Everything: transcript with hidden keys, audit log, annotations."""
    _out(_request("observer", "GET", "state"))


@observe_app.command("wait")
def observe_wait(after: Optional[int] = typer.Option(None, "--after"), timeout: float = typer.Option(60, "--timeout")) -> None:
    """Block until new events arrive."""
    _wait("observer", after, timeout)


@observe_app.command()
def annotate(seq: int, text: str, tag: Optional[str] = typer.Option(None, "--tag")) -> None:
    """Attach a note to an event (invisible to learner and teacher)."""
    _out(_request("observer", "POST", "annotate", json_body={"seq": seq, "text": text, "tag": tag}))


@observe_app.command("report")
def observe_report(category: str, text: str, seq: Optional[int] = typer.Option(None, "--seq")) -> None:
    """Report a problem."""
    _out(_request("observer", "POST", "report", json_body={"category": category, "text_md": text, "seq": seq}))
