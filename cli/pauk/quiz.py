"""Interactive quiz session."""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from pauk.client import Client

console = Console()


def run_quiz(client: Client, dir_path: str | None, recursive: bool, n: int) -> None:
    dir_id = None
    title = "all cards"
    if dir_path:
        directory = client.resolve_dir(dir_path)
        dir_id = directory["id"]
        title = dir_path
    cards = client.quiz_cards(dir_id, recursive, n)
    if not cards:
        console.print("[yellow]No cards found for this selection.[/yellow]")
        return

    console.print(f"\n[bold]Quiz:[/bold] {title} — {len(cards)} questions\n")
    score = 0
    for i, card in enumerate(cards, start=1):
        console.print(Panel(Markdown(card["question_md"]), title=f"{i}/{len(cards)}"))
        if card["type"] == "mc":
            result = _ask_mc(client, card)
        else:
            result = _ask_text(client, card)
        if result is None:  # user quit
            break
        if result:
            score += 1
        console.print()
    console.print(f"[bold]Result: {score}/{len(cards)} correct.[/bold]\n")


def _ask_mc(client: Client, card: dict) -> bool | None:
    options = card["options"]
    for idx, option in enumerate(options, start=1):
        console.print(f"  [cyan]{idx}[/cyan]) {option['text_md']}")
    raw = console.input(
        "[bold]Your choice[/bold] (numbers, comma-separated; q to quit): "
    ).strip()
    if raw.lower() == "q":
        return None
    selected = []
    for part in raw.replace(",", " ").split():
        if part.isdigit() and 1 <= int(part) <= len(options):
            selected.append(options[int(part) - 1]["id"])
    result = client.answer(card["id"], {"selected": selected})
    _show_result(result, options=options)
    return bool(result["correct"])


def _ask_text(client: Client, card: dict) -> bool | None:
    raw = console.input("[bold]Your answer[/bold] (q to quit): ").strip()
    if raw.lower() == "q":
        return None
    result = client.answer(card["id"], {"answer": raw})
    _show_result(result)
    return bool(result["correct"])


def _show_result(result: dict, options: list[dict] | None = None) -> None:
    if result["correct"]:
        note = " (typo tolerated)" if result["match"] == "typo" else ""
        console.print(f"[green]✓ correct{note}[/green]")
        return
    expected = result["expected"]
    if options is not None:
        ids = set(expected["correct_option_ids"])
        names = [o["text_md"] for o in options if o["id"] in ids]
        console.print(f"[red]✗ wrong[/red] — correct: {', '.join(names)}")
    else:
        console.print(
            f"[red]✗ wrong[/red] — accepted: {', '.join(expected['accepted_answers'])}"
        )
