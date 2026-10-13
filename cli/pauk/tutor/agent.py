"""Spawning the teacher agent (docs/tutor.md 8.1).

The default teacher is the `claude` CLI in print mode, allowed to run
only `pauk teach` commands. Another agent CLI can be plugged in with
PAUK_TUTOR_AGENT (or `pauk tutor --agent-cmd`): a command line in
which `{prompt}` is replaced by the bootstrap prompt. The agent gets
PAUK_SESSION and PAUK_TEACHER_KEY in its environment; its output is
logged next to the session transcript.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

BOOTSTRAP = (
    "You are the teacher in a pauk tutor session. A learner is waiting in a browser chat. "
    "Run `pauk teach instructions` first and follow those instructions exactly until the session has ended. "
    "Use only `pauk teach` commands."
)
RESUME = (
    " A previous teacher was disconnected: after reading the instructions, run `pauk teach attach --takeover` "
    "and `pauk teach state`, then continue where the transcript stops."
)

# one line: on Windows the claude shim is a .cmd, and cmd.exe cuts arguments at newlines
OBSERVER_PROMPT = (
    "You review a finished pauk tutor session. Run `pauk observe instructions` first and follow them; "
    "use only `pauk observe` commands."
)

DEFAULT_COMMAND = ["claude", "-p", "{prompt}", "--allowedTools", "Bash(pauk teach:*)",
                   "--output-format", "stream-json", "--verbose"]
OBSERVER_COMMAND = ["claude", "-p", "{prompt}", "--allowedTools", "Bash(pauk observe:*)",
                    "--output-format", "stream-json", "--verbose"]


def build_command(template: Optional[str], prompt: str, default: list[str] | None = None) -> list[str]:
    parts = shlex.split(template, posix=os.name != "nt") if template else list(default or DEFAULT_COMMAND)
    parts = [prompt if part == "{prompt}" else part.replace("{prompt}", prompt) for part in parts]
    exe = shutil.which(parts[0])
    if exe is None:
        raise FileNotFoundError(f"teacher agent '{parts[0]}' not found on PATH")
    parts[0] = exe
    return parts


def popen(command: list[str], **kwargs) -> subprocess.Popen:
    """Start an agent CLI in its own process group, so that stopping it
    stops its children too. npm installs claude on Windows as a .cmd
    shim, which needs cmd.exe; /s /c with one quoted string keeps
    paths with spaces intact."""
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        if command[0].lower().endswith((".cmd", ".bat")):
            return subprocess.Popen(f'cmd /d /s /c "{subprocess.list2cmdline(command)}"', **kwargs)
        return subprocess.Popen(command, **kwargs)
    return subprocess.Popen(command, start_new_session=True, **kwargs)


def kill_tree(proc: subprocess.Popen, timeout: float = 5) -> None:
    """Stop an agent and everything it started (cmd.exe -> node -> ...)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        import signal

        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        proc.kill()


class TeacherAgent:
    def __init__(self, session, env: dict[str, str], log_path: Path, template: Optional[str] = None):
        self.session = session
        self.env = env
        self.log_path = log_path
        self.template = template or os.environ.get("PAUK_TUTOR_AGENT")
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._stopping = False

    def start(self, resume: bool = False) -> None:
        with self._lock:
            if self.proc is not None and self.proc.poll() is None:
                return
            command = build_command(self.template, BOOTSTRAP + (RESUME if resume else ""))
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            log = self.log_path.open("ab")
            self.proc = popen(command, env={**os.environ, **self.env}, stdin=subprocess.DEVNULL,
                              stdout=log, stderr=subprocess.STDOUT)
            self._stopping = False
            self.session.set_agent_running(True, "started" if not resume else "restarted")
            threading.Thread(target=self._watch, args=(self.proc, log), daemon=True).start()

    def restart(self) -> None:
        self.stop()
        self.start(resume=True)

    def stop(self, timeout: float = 5) -> None:
        with self._lock:
            proc = self.proc
            self._stopping = True
        if proc is not None:
            kill_tree(proc, timeout)

    def _watch(self, proc: subprocess.Popen, log) -> None:
        code = proc.wait()
        log.close()
        with self._lock:   # a restart may have replaced the process meanwhile
            if proc is self.proc:
                detail = "stopped" if self._stopping or self.session.ended else f"exited with status {code}"
                self.session.set_agent_running(False, detail)


def default_log_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "pauk" / "sessions"


def python_teach_env() -> dict[str, str]:
    """Make sure `pauk teach` resolves to this installation for the agent."""
    bindir = str(Path(sys.executable).parent)
    path = os.environ.get("PATH", "")
    return {"PATH": path if bindir in path.split(os.pathsep) else bindir + os.pathsep + path}


def start_observer(session, env: dict[str, str], log_path: Path, template: Optional[str] = None) -> Optional[subprocess.Popen]:
    """One post-session review pass (docs/tutor.md 16.2); returns the
    process, or None when no agent CLI is available."""
    template = template or os.environ.get("PAUK_OBSERVER_AGENT")
    try:
        command = build_command(template, OBSERVER_PROMPT, OBSERVER_COMMAND)
    except FileNotFoundError:
        return None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("ab")
    proc = popen(command, env={**os.environ, **env}, stdin=subprocess.DEVNULL,
                 stdout=log, stderr=subprocess.STDOUT)
    session.emit("system", "review_started", {"log": str(log_path)}, learner=None)
    return proc
