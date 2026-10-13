"""`pauk` / `pauk tutor`: start the session host, print the link,
spawn the teacher agent (docs/tutor.md 8)."""

from __future__ import annotations

import socket
import threading
import time
import webbrowser
from typing import Callable, Optional

import uvicorn

from pauk.tutor.agent import TeacherAgent, default_log_dir, python_teach_env, start_observer
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


def run_tutor(api, port: int = 0, agent: bool = True, agent_cmd: Optional[str] = None,
              open_browser: bool = False, echo: Callable[[str], None] = print) -> Session:
    store = default_log_dir()
    session = Session(api, store_dir=store)
    port = port or free_port()
    base = f"http://127.0.0.1:{port}"
    session_url = f"{base}/s/{session.sid}"

    teacher: Optional[TeacherAgent] = None
    if agent:
        env = {"PAUK_SESSION": session_url, "PAUK_TEACHER_KEY": session.keys["teacher"], **python_teach_env()}
        teacher = TeacherAgent(session, env, store / f"{session.sid}.agent.log", agent_cmd)
    app = create_app(session, base, restart_agent=teacher.restart if teacher else None)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    learner_link = f"{session_url}/#k={session.keys['learner']}"
    echo(f"pauk tutor session {session.sid}")
    echo(f"  open:     {learner_link}")
    echo(f"  observer: {session_url}/?observer={session.keys['observer']}")
    if teacher is None:
        echo("  teacher:  tell an agent to \"connect to pauk chat "
             f"{session_url}/teach?key={session.keys['teacher']} and take over the role of the teacher\"")
    else:
        try:
            teacher.start()
            echo(f"  teacher:  agent started (log: {teacher.log_path})")
        except FileNotFoundError as e:
            echo(f"  teacher:  {e}; start one manually with "
                 f"{session_url}/teach?key={session.keys['teacher']}")
    echo("Ctrl-C to stop.")
    if open_browser:
        webbrowser.open(learner_link)

    ended_at = None
    try:
        while True:
            time.sleep(1)
            session.tick()
            if session.ended and ended_at is None:
                ended_at = time.monotonic()
                echo("Session ended; the transcript stays available until you press Ctrl-C.")
                if teacher is not None and session.settings.get("review.after_session", True):
                    reviewer = start_observer(
                        session, {"PAUK_SESSION": session_url, "PAUK_OBSERVER_KEY": session.keys["observer"],
                                  **python_teach_env()},
                        store / f"{session.sid}.review.log")
                    if reviewer is not None:
                        echo(f"  review:   an observer agent is reviewing the session (log: {store / (session.sid + '.review.log')})")
            if ended_at is not None and teacher is not None and time.monotonic() - ended_at > 60:
                teacher.stop()
    except KeyboardInterrupt:
        pass
    finally:
        session.finish("system")
        if teacher is not None:
            teacher.stop()
        server.should_exit = True
    return session
