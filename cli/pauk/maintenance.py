"""Profile maintenance from the terminal (docs/tutor.md 4.10, 16):
`pauk items` (list, show, merges, and the LLM dedup sweep),
`pauk reports` (problem reports) and `pauk triage` (an agent that
turns new reports into issues/ files on a branch)."""

from __future__ import annotations

import json
import os
import subprocess
import time
from importlib import resources
from pathlib import Path
from typing import Optional

import typer

items_app = typer.Typer(add_completion=False, rich_markup_mode=None,
                        help="Knowledge items: list, show, merge, and the duplicate sweep.")
reports_app = typer.Typer(add_completion=False, rich_markup_mode=None, invoke_without_command=True,
                          help="Problem reports filed from tutor sessions.")

DEDUP_PROMPT = ("You look for duplicate knowledge items in a pauk profile. Run `pauk items dedup-instructions` "
                "first and follow them; use only `pauk items` commands.")
TRIAGE_PROMPT = ("You triage problem reports of the pauk app into issue files. Run `pauk reports triage-instructions` "
                 "first and follow them exactly.")


def _client():
    from pauk.main import _client as client
    return client()


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=1))


def _spawn(prompt: str, tools: list[str], cwd: Path | None = None) -> int:
    from pauk.tutor.agent import build_command, python_teach_env

    command = build_command(None, prompt, ["claude", "-p", "{prompt}", "--allowedTools", *tools])
    return subprocess.run(command, cwd=cwd, env={**os.environ, **python_teach_env()}).returncode


# --- items -----------------------------------------------------------------------

@items_app.command("list")
def items_list(
    space: Optional[str] = typer.Option(None, "--space"),
    dir: Optional[str] = typer.Option(None, "--dir", help="Subject directory path (recursive)"),
    kind: Optional[str] = typer.Option(None, "--kind"),
    q: Optional[str] = typer.Option(None, "--q"),
    as_json: bool = typer.Option(False, "--json", help="Full JSON (ref, kind, label, gloss, aliases count, state)"),
) -> None:
    """List items (all pages)."""
    client = _client()
    dir_id = client.resolve_dir(dir)["id"] if dir else None
    items = list(client.iter_items(space=space, dir=dir_id, recursive="1" if dir_id else None, kind=kind, q=q))
    if as_json:
        _print([{"ref": i["ref"], "kind": i["kind"], "label_md": i["label_md"], "gloss_md": i["gloss_md"],
                 "mastery": (i["state"] or {}).get("mastery", 0)} for i in items])
        return
    for i in items:
        print(f"{i['ref']:40} {(i['state'] or {}).get('mastery', 0)}  {i['label_md']} — {i['gloss_md']}")
    print(f"{len(items)} items")


@items_app.command("show")
def items_show(ref: str) -> None:
    """One item with aliases, links, cards and recent evidence (JSON)."""
    _print(_client().get_item(ref))


@items_app.command("merge")
def items_merge(into: str, from_ref: str = typer.Argument(..., metavar="FROM"),
                reason: str = typer.Option(..., "--reason")) -> None:
    """Merge FROM into INTO now (reversible with unmerge)."""
    _print(_client().merge_items(into, {"from": from_ref, "reason": reason, "by": "human"}))


@items_app.command("unmerge")
def items_unmerge(ref: str) -> None:
    """Undo the latest merge of REF."""
    _print(_client().unmerge_item(ref))


@items_app.command("suggest-merge")
def items_suggest(into: str, from_ref: str = typer.Argument(..., metavar="FROM"),
                  reason: str = typer.Option(..., "--reason"), by: str = typer.Option("sweep", "--by")) -> None:
    """Suggest that FROM is the same as INTO (the learner decides)."""
    _print(_client().suggest_merge({"into": into, "from": from_ref, "reason": reason, "by": by}))


@items_app.command("merges")
def items_merges(status: str = typer.Option("suggested", "--status")) -> None:
    """List merge suggestions (or done/dismissed/undone merges)."""
    for m in _client().list_merges(status):
        print(f"#{m['id']} [{m['status']}] {m['from']} → {m['into']}  ({m['suggested_by']}: {m['reason']})")


@items_app.command("accept")
def items_accept(merge_id: int) -> None:
    """Accept a merge suggestion."""
    _print(_client().decide_merge(merge_id, "accept"))


@items_app.command("dismiss")
def items_dismiss(merge_id: int) -> None:
    """Dismiss a merge suggestion (the pair is recorded as distinct)."""
    _print(_client().decide_merge(merge_id, "dismiss"))


@items_app.command("dedup-instructions")
def dedup_instructions() -> None:
    """The instructions of the duplicate sweep agent."""
    print(resources.files("pauk").joinpath("dedup.md").read_text(encoding="utf-8"))


@items_app.command("dedup")
def items_dedup() -> None:
    """Start an agent that looks for duplicate items and suggests merges."""
    code = _spawn(DEDUP_PROMPT, ["Bash(pauk items:*)"])
    print("suggestions: `pauk items merges` (accept/dismiss) or the tutor's profile page")
    raise typer.Exit(code)


# --- reports and triage ---------------------------------------------------------------

@reports_app.callback()
def reports_main(ctx: typer.Context,
                 status: str = typer.Option("new", "--status", help="new, triaged, closed, or all")) -> None:
    """Without a subcommand: list reports."""
    if ctx.invoked_subcommand is not None:
        return
    items = _client().list_reports(status=None if status == "all" else status)
    if not items:
        print("no reports")
    for r in items:
        print(f"#{r['id']} [{r['status']}] {r['category']} by {r['reporter']} "
              f"({r.get('session_uid') or '-'}, seq {r.get('seq') or '-'}): {r['text_md']}")


@reports_app.command("show")
def reports_show(report_id: int) -> None:
    """One report with its session context (JSON)."""
    client = _client()
    _print(client._call("GET", f"/reports/{report_id}"))


@reports_app.command("mark")
def reports_mark(report_id: int, status: str = typer.Option(..., "--status"),
                 issue: Optional[str] = typer.Option(None, "--issue", help="e.g. issues/0016-....md")) -> None:
    """Set a report's status (and issue reference)."""
    body = {"status": status}
    if issue:
        body["issue_ref"] = issue
    _print(_client().update_report(report_id, body))


@reports_app.command("triage-instructions")
def triage_instructions() -> None:
    """The instructions of the triage agent."""
    print(resources.files("pauk").joinpath("triage.md").read_text(encoding="utf-8"))


def triage(repo: Optional[Path] = typer.Option(None, "--repo", help="pauk checkout (default: current directory)")) -> None:
    """Start an agent that turns new reports into issues/ files on a triage branch."""
    repo = (repo or Path.cwd()).resolve()
    if not (repo / "issues" / "README.md").is_file():
        print(f"{repo} is not a pauk checkout (no issues/README.md); pass --repo")
        raise typer.Exit(1)
    branch = "triage/" + time.strftime("%Y-%m-%d")
    tools = ["Read", "Grep", "Glob", "Write(issues/**)", "Edit(issues/**)",
             "Bash(pauk reports:*)", "Bash(git status)", "Bash(git diff:*)", "Bash(git log:*)",
             f"Bash(git switch -c {branch})", f"Bash(git switch {branch})", "Bash(git add issues/*)",
             "Bash(git commit:*)", "Bash(ls:*)"]
    raise typer.Exit(_spawn(TRIAGE_PROMPT + f" Today's branch is `{branch}`.", tools, cwd=repo))
