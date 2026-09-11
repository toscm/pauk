"""pauk command-line interface.

`pauk` without a subcommand launches the full-screen app
(home, deck picker, quiz, quest, route). The subcommands below
are the scripting interface for automation and content import.
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

import pauk
from pauk import config as config_mod
from pauk.client import ApiError, Client
from pauk.importer import import_file
from pauk.quiz import run_quiz
from pauk.sync import clone as clone_collection
from pauk.sync import upload as upload_collection

# rich_markup_mode=None: plain Click help text instead of rich's
# boxed panels — box-drawing output garbles on terminal resize.
app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
    rich_markup_mode=None,
)
console = Console()
_state: dict = {"server": None, "token": None, "no_cache": False}


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
    return Client(settings.server, settings.token, cache=not _state["no_cache"])


def _version_callback(value: bool) -> None:
    if value:
        print(f"pauk {pauk.__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    server: Optional[str] = typer.Option(None, "--server", help="API base URL"),
    token: Optional[str] = typer.Option(None, "--token", help="API token"),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Bypass the local read cache (always hit the API)"
    ),
    version: Optional[bool] = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True
    ),
) -> None:
    _state["server"] = server
    _state["token"] = token
    _state["no_cache"] = no_cache
    if ctx.invoked_subcommand is None:
        from pauk.tui.app import run_tui

        run_tui(_client())


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
        console.print(path or ".")
        _print_tree(client, None if path is None else client.resolve_dir(path)["id"], 1)
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


def _print_tree(client: Client, dir_id: int | None, depth: int) -> None:
    # plain indentation, no guide lines: box-drawing characters
    # garble when the terminal is resized
    if depth > 10:
        return
    for directory in client.list_dirs(dir_id):
        console.print(
            f"{'  ' * depth}{directory['name']}/ "
            f"[dim]({directory['cards']} cards, {directory['cards_total']} total)[/dim]"
        )
        if directory["subdirs"]:
            _print_tree(client, directory["id"], depth + 1)


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
def clone(directory: Path = typer.Argument(..., help="Target directory to write to")) -> None:
    """Dump the whole collection to editable markdown files."""
    clone_collection(_client(), directory, echo=console.print)


@app.command()
def upload(directory: Path = typer.Argument(..., help="Directory produced by `pauk clone`")) -> None:
    """Create NEW cards authored locally (create-only; existing cards are skipped)."""
    upload_collection(_client(), directory, echo=console.print)


cache_app = typer.Typer(add_completion=False, rich_markup_mode=None)
app.add_typer(cache_app, name="cache", help="Manage the local read cache.")


@cache_app.command("clear")
def cache_clear() -> None:
    """Delete the local read cache (all servers/users)."""
    from pauk import cache as cache_mod

    path = cache_mod.clear_all()
    console.print(f"cleared cache: {path}")


media_app = typer.Typer(add_completion=False, rich_markup_mode=None)
app.add_typer(media_app, name="media", help="Manage uploaded media files.")


@media_app.command("add")
def media_add(file: Path) -> None:
    """Upload a file; prints the URL and a markdown snippet."""
    result = _client().upload_media(file)
    console.print(f"url: {result['url']}")
    console.print(f"markdown: ![{file.stem}]({result['url']})")


@media_app.command("ls")
def media_ls() -> None:
    """List uploaded media files."""
    for item in _client().list_media():
        console.print(
            f"[dim]#{item['id']}[/dim] {item['original_name']} "
            f"({item['mime']}, {item['size']} bytes) {item['url']}"
        )


@media_app.command("rm")
def media_rm(media_id: int) -> None:
    """Delete an uploaded media file (fails if referenced)."""
    _client().delete_media(media_id)
    console.print(f"deleted media #{media_id}")


@app.command()
def health() -> None:
    """Check the server."""
    console.print(_client().health())


@app.command()
def doctor() -> None:
    """Show detected hardware and the chosen LLM provider for quests."""
    from pauk.llm.hardware import choose_provider, detect_hardware

    hw = detect_hardware()
    accel = {"metal": "Metal (Apple GPU)", "cuda": "NVIDIA CUDA", "none": "CPU only"}
    console.print("[bold]Machine[/bold]")
    console.print(f"  RAM: {hw.ram_gb:.0f} GB · {hw.arch} · {hw.system}")
    console.print(f"  accelerator: {accel[hw.accelerator]}")
    provider = choose_provider(hw)
    console.print("\n[bold]Quest LLM[/bold]")
    console.print(f"  provider: {provider.detail}")
    if provider.model:
        console.print(
            f"  local model: {provider.model.label} "
            f"(~{provider.model.params_b}B params)"
        )
        console.print(
            "  [dim]install the `claude` CLI for a stronger model with no download[/dim]"
        )

    _report_image_support()


def _report_image_support() -> None:
    """Terminal image capability + which renderer pauk will use. Run
    this in the terminal where images look wrong (e.g. over SSH in
    Windows Terminal) to see whether crisp images (sixel/kitty) are
    available or pauk is falling back to the half-block renderer."""
    import os

    in_tmux = bool(os.environ.get("TMUX"))
    is_tty = sys.stdout.isatty()
    console.print("\n[bold]Terminal images[/bold]")
    console.print(f"  TERM={os.environ.get('TERM', '?')} · tty={is_tty} · tmux={in_tmux}")

    sixel_ok = tgp_ok = False
    try:
        from textual_image.renderable import sixel, tgp

        sixel_ok = bool(is_tty and sixel.query_terminal_support())
        tgp_ok = bool(is_tty and tgp.query_terminal_support())
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        console.print(f"  (could not probe terminal: {exc})")

    console.print(f"  sixel: {'yes' if sixel_ok else 'no'} · "
                  f"kitty/TGP: {'yes' if tgp_ok else 'no'}")

    mode = os.environ.get("PAUK_IMAGE_MODE") or config_mod.get("image_mode") or "auto"
    passthrough = config_mod.get("tmux_image_passthrough")
    if mode != "auto":
        chosen = mode
    elif in_tmux and not passthrough:
        chosen = "halfcell (tmux without passthrough)"
    elif tgp_ok:
        chosen = "kitty/TGP"
    elif sixel_ok:
        chosen = "sixel"
    else:
        chosen = "halfcell (no high-fidelity protocol detected)"
    console.print(f"  image_mode={mode} · tmux_image_passthrough={passthrough}")
    console.print(f"  renderer: {chosen}")

    if "halfcell" in chosen and (sixel_ok or tgp_ok):
        console.print(
            "  [dim]a crisp protocol is available but unused; in tmux set "
            "tmux_image_passthrough=true (docs/images.md) or "
            "PAUK_IMAGE_MODE=sixel[/dim]"
        )
    elif "halfcell" in chosen:
        console.print(
            "  [dim]no sixel/kitty advertised, so images use half-blocks. "
            "Windows Terminal needs v1.22+ for sixel (kitty isn't supported "
            "there); try PAUK_IMAGE_MODE=sixel to test anyway[/dim]"
        )


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
    cards: int = typer.Option(0, "--cards", help="Also list the N hardest cards"),
) -> None:
    """Show answer statistics and the top 5 decks."""
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
    decks = client.quiz_dirs()
    if path:
        decks = [d for d in decks if d["path"] == path or d["path"].startswith(path + "/")]
    decks = [d for d in decks if d["runs"] > 0][:5]
    if decks:
        console.print("[bold]Top decks[/bold] (most played):")
        for deck in decks:
            p = deck.get("performance")
            perf = f"{round(p * 100):+d}%" if p is not None else "no data"
            runs = "run" if deck["runs"] == 1 else "runs"
            console.print(
                f"  {deck['runs']:>3} {runs}  {deck['path']} "
                f"[dim]({deck['cards_total']} cards, performance {perf})[/dim]"
            )
    else:
        console.print("[dim]No quiz runs yet.[/dim]")
    if cards > 0 and data["items"]:
        console.print(f"\n[bold]Hardest cards[/bold] (worst {min(cards, len(data['items']))}):")
        for item in data["items"][:cards]:
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
