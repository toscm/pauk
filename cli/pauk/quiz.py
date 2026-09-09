"""Interactive quiz session.

Deliberately plain output: no panels or box-drawing characters
(they garble on terminal resize), no persistent status bar. The
selection mode, best runs, and shortcuts are printed once at the
start; the ranking (with trophy) at the end.
"""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown

from pauk.client import Client

console = Console()

TROPHY = "\n".join([
    "      ___________",
    "     '._==_==_=_.'",
    "     .-\\:      /-.",
    "    | (|:.     |) |",
    "     '-|:.     |-'",
    "       \\::.    /",
    "        '::. .'",
    "          ) (",
    "        _.' '._",
    "       `\"\"\"\"\"\"\"`",
])


def run_quiz(client: Client, dir_path: str | None, recursive: bool, n: int) -> None:
    dir_id = None
    title = "all cards"
    best = None
    if dir_path:
        directory = client.resolve_dir(dir_path)
        dir_id = directory["id"]
        title = dir_path
        for entry in client.quiz_dirs():
            if entry["id"] == dir_id:
                best = entry["best"]
                break
    cards = client.quiz_cards(dir_id, recursive, n)
    if not cards:
        console.print("[yellow]No cards found for this selection.[/yellow]")
        return

    best_text = f"{best['correct']}/{best['total']}" if best else "none yet"
    console.print(f"\n[bold]Quiz: {title}[/bold] — {len(cards)} questions")
    console.print(
        "[dim]Mode: weighted pick (new, often-wrong, and stale cards first) "
        f"· Best run: {best_text} · q = quit[/dim]\n"
    )

    run_id = client.start_run(dir_id, len(cards))
    score = 0
    answered = 0
    for i, card in enumerate(cards, start=1):
        console.print(f"[bold cyan]{i}/{len(cards)}[/bold cyan]")
        console.print(Markdown(card["question_md"]))
        if card["type"] == "mc":
            result = _ask_mc(client, card)
        else:
            result = _ask_text(client, card)
        if result is None:  # user quit
            break
        answered += 1
        if result:
            score += 1
        console.print()

    console.print(f"[bold]Result: {score}/{answered} correct.[/bold]")
    summary = client.finish_run(run_id, score, answered)
    _show_ranking(summary)


def _show_ranking(summary: dict) -> None:
    top = summary.get("top") or []
    if top:
        console.print("[bold]Top runs:[/bold]")
        for i, run in enumerate(top, start=1):
            date = run["finished_at"][:10]
            console.print(f"  {i}. {run['correct']}/{run['total']}  ({date})")
    rank = summary.get("rank")
    if rank is not None:
        console.print(f"[bold yellow]{TROPHY}[/bold yellow]")
        console.print(f"[bold yellow]New top-{len(top)} run — place #{rank}![/bold yellow]\n")


def _ask_mc(client: Client, card: dict) -> bool | None:
    options = card["options"]
    for idx, option in enumerate(options, start=1):
        console.print(f"  [cyan]{idx}[/cyan]) {option['text_md']}")
    raw = console.input("[bold]Your choice[/bold]: ").strip()
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
    raw = console.input("[bold]Your answer[/bold]: ").strip()
    if raw.lower() == "q":
        return None
    result = client.answer(card["id"], {"answer": raw})
    _show_result(result)
    return bool(result["correct"])


def _show_result(result: dict, options: list[dict] | None = None) -> None:
    expected = result["expected"]
    if result["correct"]:
        if result["match"] == "typo":
            spelling = expected["accepted_answers"][0]
            console.print(
                f"[green]✓ correct[/green] — typo tolerated, "
                f"correct spelling: [bold]{spelling}[/bold]"
            )
        else:
            console.print("[green]✓ correct[/green]")
        return
    if options is not None:
        ids = set(expected["correct_option_ids"])
        names = [o["text_md"] for o in options if o["id"] in ids]
        console.print(f"[red]✗ wrong[/red] — correct: [bold]{', '.join(names)}[/bold]")
    else:
        console.print(
            f"[red]✗ wrong[/red] — accepted: "
            f"[bold]{', '.join(expected['accepted_answers'])}[/bold]"
        )
