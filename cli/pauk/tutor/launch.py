"""`pauk` / `pauk tutor`: start the session host, print the link,
spawn the teacher agent (docs/tutor.md 8)."""

from __future__ import annotations

import socket
import threading
import time
import webbrowser
from typing import Callable, Optional

import uvicorn

from pathlib import Path

from pauk.tutor.agent import (TeacherAgent, default_log_dir, kill_tree, python_teach_env, start_learner,
                              start_observer)
from pauk.tutor.host import create_app
from pauk.tutor.session import Session

DEFAULT_PORT = 8765


def free_port(preferred: int = DEFAULT_PORT) -> int:
    for port in (preferred, 0):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return sock.getsockname()[1]
    raise RuntimeError("no free port")


class SessionRun:
    """One session with its teacher agent and post-session reviewer."""

    def __init__(self, session: Session, teacher: Optional[TeacherAgent], app):
        self.session = session
        self.teacher = teacher
        self.app = app
        self.ended_at: Optional[float] = None
        self.reviewer = None
        self.closed = False


class Host:
    """The ASGI app of `pauk tutor`: routes /s/<sid>/... to the app of
    that session. A finished session can start the next one from the
    browser ("New session"), so one `pauk tutor` serves any number of
    sessions in a row; old ones stay readable until Ctrl-C."""

    def __init__(self, api, store: Path, base: str, agent: bool, agent_cmd: Optional[str],
                 simulation: bool, echo: Callable[[str], None]):
        self.api, self.store, self.base = api, store, base
        self.agent, self.agent_cmd, self.simulation, self.echo = agent, agent_cmd, simulation, echo
        self.runs: dict[str, SessionRun] = {}
        self.lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while (await receive())["type"] != "lifespan.shutdown":
                await send({"type": "lifespan.startup.complete"})
            await send({"type": "lifespan.shutdown.complete"})
            return
        parts = scope.get("path", "").split("/")
        run = self.runs.get(parts[2]) if len(parts) > 2 and parts[1] == "s" else None
        if run is None:
            await send({"type": "http.response.start", "status": 404, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"no such session"})
            return
        await run.app(scope, receive, send)

    def learner_link(self, session: Session) -> str:
        return f"{self.base}/s/{session.sid}/#k={session.keys['learner']}"

    def new_session(self) -> SessionRun:
        with self.lock:
            session = Session(self.api, store_dir=self.store, simulation=self.simulation)
            session_url = f"{self.base}/s/{session.sid}"
            teacher = None
            if self.agent:
                env = {"PAUK_SESSION": session_url, "PAUK_TEACHER_KEY": session.keys["teacher"], **python_teach_env()}
                teacher = TeacherAgent(session, env, self.store / f"{session.sid}.agent.log", self.agent_cmd)
            app = create_app(session, self.base, restart_agent=teacher.restart if teacher else None,
                             new_session=None if self.simulation else self.next_session)
            run = SessionRun(session, teacher, app)
            self.runs[session.sid] = run
        self.echo(f"pauk tutor session {session.sid}")
        self.echo(f"  open:     {self.learner_link(session)}")
        self.echo(f"  observer: {session_url}/?observer={session.keys['observer']}")
        if teacher is None:
            self.echo("  teacher:  tell an agent to \"connect to pauk chat "
                      f"{session_url}/teach?key={session.keys['teacher']} and take over the role of the teacher\"")
        else:
            try:
                teacher.start()
                self.echo(f"  teacher:  agent started (log: {teacher.log_path})")
            except FileNotFoundError as e:
                self.echo(f"  teacher:  {e}; start one manually with "
                          f"{session_url}/teach?key={session.keys['teacher']}")
        return run

    def next_session(self) -> str:
        """Called by a finished session's "New session": the new learner link."""
        return self.learner_link(self.new_session().session)

    def tick(self) -> None:
        """Per second: session timers, the review after a session, and
        stopping a teacher a minute after its session ended."""
        for run in list(self.runs.values()):
            if run.closed:
                continue
            session = run.session
            session.tick()
            if session.ended and run.ended_at is None:
                run.ended_at = time.monotonic()
                self.echo(f"Session {session.sid} ended; the transcript stays available until you press Ctrl-C.")
                if run.teacher is not None and session.settings.get("review.after_session", True):
                    sid = session.sid
                    run.reviewer = start_observer(
                        session, {"PAUK_SESSION": f"{self.base}/s/{sid}", "PAUK_OBSERVER_KEY": session.keys["observer"],
                                  **python_teach_env()},
                        self.store / f"{sid}.review.log")
                    if run.reviewer is not None:
                        self.echo(f"  review:   an observer agent is reviewing the session (log: {self.store / (sid + '.review.log')})")
            if run.ended_at is not None and run.teacher is not None and time.monotonic() - run.ended_at > 60:
                run.teacher.stop()
                run.closed = run.reviewer is None or run.reviewer.poll() is not None

    def close(self) -> None:
        for run in self.runs.values():
            run.session.finish("system")
            if run.teacher is not None:
                run.teacher.stop()
            if run.reviewer is not None:
                kill_tree(run.reviewer)


def run_tutor(api, port: int = 0, agent: bool = True, agent_cmd: Optional[str] = None,
              open_browser: bool = False, echo: Callable[[str], None] = print,
              persona: Optional[Path] = None, review_timeout: float = 900) -> Session:
    """Run sessions until Ctrl-C. With a persona (simulation), a learner
    agent plays the learner and the function returns once the session
    and its review are over."""
    store = default_log_dir()
    port = port or free_port()
    base = f"http://127.0.0.1:{port}"
    host = Host(api, store, base, agent, agent_cmd, persona is not None, echo)
    server = uvicorn.Server(uvicorn.Config(host, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    first = host.new_session()
    session = first.session
    learner_proc = None
    if persona is not None:
        learner_proc = start_learner({"PAUK_SESSION": f"{base}/s/{session.sid}", "PAUK_LEARNER_KEY": session.keys["learner"],
                                      "PAUK_PERSONA": str(persona.resolve()), **python_teach_env()},
                                     store / f"{session.sid}.learner.log")
        echo(f"  learner:  simulated ({persona.name}; log: {store / (session.sid + '.learner.log')})")
    echo("Ctrl-C to stop.")
    if open_browser:
        webbrowser.open(host.learner_link(session))

    try:
        while True:
            time.sleep(1)
            host.tick()
            if persona is not None and first.ended_at is not None:
                review_done = first.reviewer is None or first.reviewer.poll() is not None
                if review_done or time.monotonic() - first.ended_at > review_timeout:
                    break
    except KeyboardInterrupt:
        pass
    finally:
        host.close()
        if learner_proc is not None:
            kill_tree(learner_proc)
        server.should_exit = True
    return session
