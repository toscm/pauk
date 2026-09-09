"""pauk command-line interface.

`pauk` without a subcommand opens the interactive menu; every
menu action is also a direct subcommand for scripting.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

try:
    # Enables arrow keys / line editing for every input() prompt.
    import readline  # noqa: F401
except ImportError:  # pragma: no cover - Windows
    pass

import typer
from rich.console import Console
from rich.tree import Tree

import pauk
from pauk import config as config_mod
from pauk.client import ApiError, Client
from pauk.fuzzy import fuzzy_filter
from pauk.importer import import_file
from pauk.quiz import run_quiz

app = typer.Typer(add_completion=False, invoke_without_command=True, no_args_is_help=False)
console = Console()
_state: dict = {"server": None, "token": None}


def run() -> None:
    try:
        app()
    except ApiError as e:
        console.print(f"[red]API error ({e.status}):[/red] {e}")
        sys.exit(1)


def _client() -> Client:
    settings = config_mod.load(_state["server"], _state["token"])
    if not settings.server or not settings.token:
        console.print(
            "[red]No server/token configured.[/red] "
            "Run [bold]pauk config SERVER TOKEN[/bold] "
            "(or set PAUK_SERVER / PAUK_TOKEN)."
        )
        raise typer.Exit(1)
    return Client(settings.server, settings.token)


def _version_callback(value: bool) -> None:
    if value:
        print(f"pauk {pauk.__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    server: Optional[str] = typer.Option(None, "--server", help="API base URL"),
    token: Optional[str] = typer.Option(None, "--token", help="API token"),
    version: Optional[bool] = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True
    ),
) -> None:
    _state["server"] = server
    _state["token"] = token
    if ctx.invoked_subcommand is None:
        _menu()


@app.command()
def config(
    server: Optional[str] = typer.Argument(None),
    token: Optional[str] = typer.Argument(None),
) -> None:
    """Show the configuration, or store SERVER and TOKEN."""
    if server is None:
        settings = config_mod.load()
        console.print(f"config file: {config_mod.CONFIG_PATH}")
        console.print(f"server: {settings.server or '[not set]'}")
        console.print(f"token: {'[set]' if settings.token else '[not set]'}")
        return
    if token is None:
        console.print("[red]Provide SERVER and TOKEN together.[/red]")
        raise typer.Exit(1)
    config_mod.save(server, token)
    console.print(f"Saved to {config_mod.CONFIG_PATH}")


@app.command()
def ls(
    path: Optional[str] = typer.Argument(None, help="Directory path, e.g. italian/verbs"),
    tree: bool = typer.Option(False, "--tree", help="Show the whole subtree"),
) -> None:
    """List directories (and their card counts)."""
    client = _client()
    if tree:
        root = Tree(path or ".")
        _fill_tree(client, root, None if path is None else client.resolve_dir(path)["id"])
        console.print(root)
        return
    if path is None:
        dirs = client.list_dirs()
    else:
        dirs = client.list_dirs(client.resolve_dir(path)["id"])
    for directory in dirs:
        console.print(
            f"{directory['name']}/  "
            f"[dim]({directory['cards']} cards, {directory['cards_total']} total)[/dim]"
        )
    if path is not None:
        for card in _client().iter_cards(dir=client.resolve_dir(path)["id"]):
            question = card["question_md"].replace("\n", " ")
            console.print(f"[dim]#{card['id']}[/dim] {question[:70]}")


def _fill_tree(client: Client, node: Tree, dir_id: int | None, depth: int = 0) -> None:
    if depth > 10:
        return
    for directory in client.list_dirs(dir_id):
        label = (
            f"{directory['name']}/ "
            f"({directory['cards']} cards, {directory['cards_total']} total)"
        )
        child = node.add(label)
        if directory["subdirs"]:
            _fill_tree(client, child, directory["id"], depth + 1)


@app.command()
def mkdir(path: str) -> None:
    """Create a directory path (mkdir -p style)."""
    client = _client()
    parts = path.strip("/").split("/")
    parent_id = None
    built = []
    for name in parts:
        built.append(name)
        try:
            parent_id = client.resolve_dir("/".join(built))["id"]
        except ApiError as e:
            if e.code != "not_found":
                raise
            parent_id = client.create_dir(name, parent_id)["id"]
    console.print(f"ok: {path}")


@app.command()
def add(
    directory: Optional[str] = typer.Option(None, "--dir", help="Target directory path"),
) -> None:
    """Add a card interactively."""
    client = _client()
    dir_ids = []
    if directory:
        dir_ids = [client.resolve_dir(directory)["id"]]
    card_type = console.input("Type ([bold]text[/bold]/mc): ").strip() or "text"
    question = console.input("Question (markdown): ").strip()
    body: dict = {"type": card_type, "question_md": question, "dirs": dir_ids}
    if card_type == "mc":
        options = []
        console.print("Enter options; prefix the correct one(s) with '*'. Empty line ends.")
        while True:
            raw = console.input(f"option {len(options) + 1}: ").strip()
            if not raw:
                break
            correct = raw.startswith("*")
            options.append({"text_md": raw.lstrip("* "), "correct": correct})
        body["options"] = options
    else:
        answers = []
        console.print("Accepted answers, one per line. Empty line ends.")
        while True:
            raw = console.input(f"answer {len(answers) + 1}: ").strip()
            if not raw:
                break
            answers.append(raw)
        body["accepted_answers"] = answers
    card = client.create_card(body)
    console.print(f"created card #{card['id']}")


@app.command()
def rm(card_id: int) -> None:
    """Delete a card by id."""
    _client().delete_card(card_id)
    console.print(f"deleted card #{card_id}")


@app.command()
def quiz(
    directory: Optional[str] = typer.Option(None, "--dir", help="Directory path to quiz"),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive"),
    n: int = typer.Option(20, "-n", help="Number of questions"),
) -> None:
    """Start a quiz."""
    run_quiz(_client(), directory, recursive, n)


@app.command(name="import")
def import_cmd(file: Path) -> None:
    """Import a content JSON file (dirs + cards)."""
    import_file(_client(), file, echo=console.print)


@app.command()
def health() -> None:
    """Check the server."""
    console.print(_client().health())


@app.command()
def login(server: str) -> None:
    """Store SERVER and an interactively entered token."""
    token = typer.prompt("Token", hide_input=True).strip()
    client = Client(server, token)
    client.list_dirs()  # raises 401 on a bad token
    config_mod.save(server, token)
    console.print(f"[green]Logged in.[/green] Saved to {config_mod.CONFIG_PATH}")


@app.command()
def stats(
    path: Optional[str] = typer.Argument(None, help="Directory path (default: everything)"),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive"),
    worst: int = typer.Option(10, "--worst", help="How many worst cards to list"),
) -> None:
    """Show answer statistics for a directory (or everything)."""
    client = _client()
    dir_id = client.resolve_dir(path)["id"] if path else None
    data = client.stats(dir_id, recursive)
    summary = data["summary"]
    accuracy = "-" if summary["accuracy"] is None else f"{summary['accuracy']:.0%}"
    console.print(f"\n[bold]Stats: {path or 'all cards'}[/bold]")
    console.print(
        f"cards: {summary['cards']} · asked at least once: {summary['asked_cards']} "
        f"· answers: {summary['reviews']} · accuracy: {accuracy}\n"
    )
    if data["items"]:
        console.print(f"[bold]Hardest cards[/bold] (worst {min(worst, len(data['items']))}):")
        for item in data["items"][:worst]:
            question = item["question_md"].replace("\n", " ")[:60]
            console.print(
                f"  {item['accuracy']:>4.0%}  {item['correct']}/{item['asked']}  "
                f"[dim]#{item['id']}[/dim] {question}"
            )


@app.command()
def update() -> None:
    """Update pauk to the newest version (git pull + reinstall)."""
    repo = Path(pauk.__file__).resolve().parents[2]
    if not (repo / ".git").is_dir():
        console.print(
            "[red]Not a git checkout.[/red] Reinstall via toscpm "
            "(toscpm install) or pip."
        )
        raise typer.Exit(1)
    console.print(f"Updating {repo} ...")
    pull = subprocess.run(
        ["git", "-C", str(repo), "pull", "--ff-only"],
        capture_output=True, text=True,
    )
    console.print(pull.stdout.strip() or pull.stderr.strip())
    if pull.returncode != 0:
        raise typer.Exit(1)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "-e", str(repo / "cli")],
        check=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "pauk", "--version"], capture_output=True, text=True
    )
    console.print(f"[green]Now at {result.stdout.strip()}[/green]")


def _menu() -> None:
    while True:
        console.print(
            "\n[bold]pauk[/bold] — what do you want to do?\n"
            "  [cyan]1[/cyan]) Start a new quiz\n"
            "  [cyan]2[/cyan]) Organize questions\n"
            "  [cyan]3[/cyan]) Configure settings\n"
            "  [cyan]4[/cyan]) Exit"
        )
        choice = console.input("> ").strip()
        if choice == "1":
            _menu_quiz()
        elif choice == "2":
            _menu_organize()
        elif choice == "3":
            config(None, None)
        elif choice in {"4", "q", ""}:
            return
        else:
            console.print("[yellow]Please choose 1-4.[/yellow]")


def _menu_quiz() -> None:
    client = _client()
    all_dirs = [d for d in client.quiz_dirs() if d["cards_total"] > 0]
    if not all_dirs:
        console.print("[yellow]No quizzes yet — import some content first.[/yellow]")
        return
    shown = all_dirs
    query = ""
    while True:
        label = f"matching '{query}'" if query else "favorites first"
        console.print(f"\nChoose a quiz ({label}):")
        console.print("  [cyan]0[/cyan]) all cards")
        for idx, entry in enumerate(shown[:9], start=1):
            best = (
                f", best {entry['best']['correct']}/{entry['best']['total']}"
                if entry["best"] else ""
            )
            console.print(
                f"  [cyan]{idx}[/cyan]) {entry['path']} "
                f"({entry['cards_total']} cards{best})"
            )
        raw = console.input(
            "[dim]number = start, text = search, Enter = back[/dim] > "
        ).strip()
        if raw == "":
            return
        if raw.isdigit():
            if int(raw) == 0:
                path = None
                break
            if 1 <= int(raw) <= len(shown[:9]):
                path = shown[int(raw) - 1]["path"]
                break
            continue
        query = raw
        shown = fuzzy_filter(query, all_dirs, key=lambda d: d["path"])
        if not shown:
            console.print("[yellow]No match.[/yellow]")
            shown = all_dirs
            query = ""
    raw_n = console.input("How many questions? [20] ").strip()
    n = int(raw_n) if raw_n.isdigit() and int(raw_n) > 0 else 20
    run_quiz(client, path, recursive=True, n=n)


def _menu_organize() -> None:
    console.print(
        "\nOrganizing works via subcommands for now:\n"
        "  pauk ls --tree          show all folders\n"
        "  pauk mkdir PATH         create a folder path\n"
        "  pauk add --dir PATH     add a card\n"
        "  pauk rm ID              delete a card\n"
        "  pauk import FILE.json   import content"
    )
