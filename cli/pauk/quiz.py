"""Interactive quiz session.

Deliberately plain output: no panels or box-drawing characters
(they garble on terminal resize), no persistent status bar. The
selection mode, best runs, and shortcuts are printed once at the
start; the ranking (with trophy) at the end.
"""

from __future__ import annotations

import random

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

    best_text = f"{round(best['accuracy'] * 100)}%" if best else "none yet"
    console.print(f"\n[bold]Quiz: {title}[/bold] — {len(cards)} questions")
    console.print(
        "[dim]Mode: weighted pick (new, often-wrong, and stale cards first) "
        f"· Best run: {best_text} · q = quit[/dim]\n"
    )

    ranked = True
    while True:
        quit_early, wrong_cards = _run_once(client, dir_id, cards, ranked)
        if quit_early:
            return
        prompt = "[bold]r[/bold] = repeat"
        if wrong_cards:
            prompt += f" · [bold]w[/bold] = repeat the {len(wrong_cards)} wrong"
        try:
            choice = console.input(f"{prompt} · Enter = done > ").strip().lower()
        except EOFError:
            return
        if choice == "r":
            cards = random.sample(cards, len(cards))
        elif choice == "w" and wrong_cards:
            cards = random.sample(wrong_cards, len(wrong_cards))
        else:
            return
        # repeats are practice, not ranked
        ranked = False
        console.print()


def _run_once(client: Client, dir_id: int | None, cards: list[dict], ranked: bool = True) -> tuple[bool, list[dict]]:
    """One pass over cards. Returns (quit_early, wrong_cards)."""
    run_id = client.start_run(dir_id, len(cards), ranked)["id"]
    score = 0
    answered = 0
    wrong_cards = []
    quit_early = False
    for i, card in enumerate(cards, start=1):
        console.print(f"[bold cyan]{i}/{len(cards)}[/bold cyan]")
        console.print(Markdown(card["question_md"]))
        if card["type"] == "mc":
            result = _ask_mc(client, card)
        else:
            result = _ask_text(client, card)
        if result is None:
            quit_early = True
            break
        answered += 1
        if result:
            score += 1
        else:
            wrong_cards.append(card)
        console.print()

    console.print(f"[bold]Result: {score}/{answered} correct.[/bold]")
    summary = client.finish_run(run_id, score, answered)
    _show_ranking(summary)
    return quit_early, wrong_cards


def _show_ranking(summary: dict) -> None:
    top = summary.get("top") or []
    if top:
        console.print("[bold]Top runs:[/bold]")
        for i, run in enumerate(top, start=1):
            date = run["finished_at"][:10]
            console.print(
                f"  {i}. {round(run['accuracy'] * 100)}%  "
                f"({run['correct']}/{run['total']}, {date})"
            )
    rank = summary.get("rank")
    if rank is not None:
        console.print(f"[bold yellow]{TROPHY}[/bold yellow]")
        console.print(f"[bold yellow]New top-{len(top)} run — place #{rank}![/bold yellow]\n")


def _input(prompt: str) -> str:
    try:
        return console.input(prompt)
    except EOFError:
        return "q"


def _ask_mc(client: Client, card: dict) -> bool | None:
    options = card["options"]
    for idx, option in enumerate(options, start=1):
        console.print(f"  [cyan]{idx}[/cyan]) {option['text_md']}")
    raw = _input("[bold]Your choice[/bold]: ").strip()
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
    raw = _input("[bold]Your answer[/bold]: ").strip()
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
