"""`pauk learn`: the learner's counterpart of `pauk teach` (docs/tutor.md
15.2). It calls exactly the endpoints the browser calls, so an LLM can
play the learner in simulations without a browser; if something cannot
be done through `pauk learn`, the API is incomplete.

The session comes from `--session URL` (with `?key=`) or PAUK_SESSION +
PAUK_LEARNER_KEY.
"""

from __future__ import annotations

import json
from typing import Optional

import typer

from pauk.tutor import teach as t

learn_app = typer.Typer(add_completion=False, rich_markup_mode=None,
                        help="Learner commands for a running tutor session (simulations, scripting).")

ROLE = "learner"


def _post(path: str, body: dict) -> None:
    t._out(t._request(ROLE, "POST", path, json_body=body))


@learn_app.callback()
def learn_main(session: Optional[str] = typer.Option(None, "--session", help="Session URL (may include ?key=...)")) -> None:
    t._ctx["session"] = session


@learn_app.command()
def instructions() -> None:
    """How to play the learner."""
    import os
    from importlib import resources
    from pathlib import Path

    print(resources.files("pauk.tutor").joinpath("learner.md").read_text(encoding="utf-8"))
    persona = os.environ.get("PAUK_PERSONA")
    if persona:
        print("\n## Your persona\n")
        print(Path(persona).read_text(encoding="utf-8"))


@learn_app.command()
def state() -> None:
    """Goal, status and every event you can see."""
    t._out(t._request(ROLE, "GET", "state"))


@learn_app.command()
def wait(after: Optional[int] = typer.Option(None, "--after"), timeout: float = typer.Option(60, "--timeout")) -> None:
    """Block until the teacher does something (max --timeout seconds)."""
    t._wait(ROLE, after, timeout)


@learn_app.command()
def start(dirs: list[str] = typer.Option([], "--dir", help="Subject path, repeatable"),
          mode: str = typer.Option("mixed", "--mode"), minutes: int = typer.Option(15, "--minutes")) -> None:
    """Choose the goal of the session."""
    _post("start", {"dirs": dirs, "mode": mode, "minutes": minutes})


@learn_app.command()
def say(text: str) -> None:
    """Send a chat message to the teacher."""
    _post("message", {"text": text})


@learn_app.command()
def answer(exercise_id: str, text: Optional[str] = typer.Option(None, "--text"),
           selected: list[str] = typer.Option([], "--selected", help="mc option id, repeatable"),
           matches: Optional[str] = typer.Option(None, "--matches", help='JSON: {"0": "<token>", ...}')) -> None:
    """Answer an exercise (text/open: --text; mc: --selected; match: --matches)."""
    body: dict = {"exercise_id": exercise_id}
    if text is not None:
        body["text"] = text
    if selected:
        body["selected"] = selected
    if matches:
        body["matches"] = json.loads(matches)
    _post("answer", body)


@learn_app.command("dont-know")
def dont_know(exercise_id: str) -> None:
    """Give up on an exercise."""
    _post("dont-know", {"exercise_id": exercise_id})


@learn_app.command()
def hint(exercise_id: str) -> None:
    """Ask for a hint."""
    _post("hint-request", {"exercise_id": exercise_id})


@learn_app.command()
def reveal(exercise_id: str) -> None:
    """Reveal the reference answer of a recall exercise."""
    _post("reveal", {"exercise_id": exercise_id})


@learn_app.command("self-grade")
def self_grade(exercise_id: str, correct: bool = typer.Option(..., "--correct/--wrong")) -> None:
    """Grade yourself after revealing."""
    _post("self-grade", {"exercise_id": exercise_id, "correct": correct})


@learn_app.command()
def proposal(proposal_id: str, action: str = typer.Argument(..., help="add, add_anyway, use_existing, dismiss"),
             ref: Optional[str] = typer.Option(None, "--ref")) -> None:
    """Decide on an item the teacher proposed."""
    _post("proposal", {"proposal_id": proposal_id, "action": action, "ref": ref})


@learn_app.command()
def activity(aid: str, action: str = typer.Argument(..., help='JSON, e.g. {"drive": "nuernberg"}')) -> None:
    """Act in an activity."""
    _post("activity", {"aid": aid, "action": t._json_arg(action)})


@learn_app.command()
def report(category: str, text: str, seq: Optional[int] = typer.Option(None, "--seq")) -> None:
    """Report a problem with the session or the app."""
    _post("report", {"category": category, "text_md": text, "seq": seq})


@learn_app.command()
def end() -> None:
    """End the session."""
    _post("end", {})
