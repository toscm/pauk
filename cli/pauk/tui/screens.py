"""Screens of the pauk TUI: Home → Picker → Quiz → Result."""

from __future__ import annotations

import io
import random
import re

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Input,
    Markdown,
    OptionList,
    SelectionList,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

from pauk.fuzzy import fuzzy_filter

LOGO = r"""
                        _
  _ __    __ _  _   _  | | __
 | '_ \  / _` || | | | | |/ /
 | |_) || (_| || |_| | |   <
 | .__/  \__,_| \__,_| |_|\_\
 |_|
"""

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


class HomeScreen(Screen):
    BINDINGS = [Binding("q", "app.quit", "Quit")]

    def compose(self) -> ComposeResult:
        with Vertical(id="home"):
            yield Static(LOGO, id="logo")
            yield Static("the flashcard trainer", id="tagline")
            yield OptionList(
                Option("Start a quiz", id="quiz"),
                Option("Statistics", id="stats"),
                Option("Quit", id="quit"),
                id="home-menu",
            )
        yield Footer()

    def on_mount(self) -> None:
        menu = self.query_one("#home-menu", OptionList)
        menu.highlighted = 0
        menu.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == "quiz":
            self.app.push_screen(PickerScreen())
        elif event.option.id == "stats":
            self.app.push_screen(StatsScreen())
        else:
            self.app.exit()


class DeckTree(Tree):
    """Tree with the requested navigation: Right enters a
    directory, Left leaves it (or jumps to the parent)."""

    BINDINGS = [
        Binding("right", "enter_dir", "Enter dir", show=True),
        Binding("left", "leave_dir", "Leave dir", show=True),
    ]

    def action_enter_dir(self) -> None:
        node = self.cursor_node
        if node is not None and node.allow_expand and not node.is_expanded:
            node.expand()

    def action_leave_dir(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded and node.allow_expand:
            node.collapse()
        elif node.parent is not None and node.parent is not self.root:
            self.move_cursor(node.parent)


class PickerScreen(Screen):
    """Deck selection: favorites list (filterable) and directory
    tree. View/expansion/filter state is kept on the app so it
    survives leaving and re-entering the picker."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("f2", "toggle_view", "Favorites/Tree"),
    ]

    def action_toggle_view(self) -> None:
        tabs = self.query_one("#picker-tabs", TabbedContent)
        tabs.active = "tree" if tabs.active == "fav" else "fav"
        self._focus_active_view()

    def _focus_active_view(self) -> None:
        tabs = self.query_one("#picker-tabs", TabbedContent)
        if tabs.active == "tree":
            self.query_one("#deck-tree", DeckTree).focus()
        else:
            self.query_one("#filter", Input).focus()

    def compose(self) -> ComposeResult:
        with TabbedContent(id="picker-tabs"):
            with TabPane("Favorites", id="fav"):
                yield Input(placeholder="type to filter ...", id="filter")
                yield OptionList(id="fav-list")
            with TabPane("Tree", id="tree"):
                yield DeckTree("decks", id="deck-tree")
        yield Footer()

    @property
    def _memory(self) -> dict:
        app = self.app
        if not hasattr(app, "picker_memory"):
            app.picker_memory = {"tab": "fav", "expanded": set(), "filter": ""}
        return app.picker_memory

    def on_mount(self) -> None:
        self.entries = [
            e for e in self.app.client.quiz_dirs() if e["cards_total"] > 0
        ]
        filter_input = self.query_one("#filter", Input)
        filter_input.value = self._memory["filter"]
        self._rebuild_favorites()
        self._build_tree()
        tabs = self.query_one("#picker-tabs", TabbedContent)
        tabs.active = self._memory["tab"]
        self.call_after_refresh(self._focus_active_view)

    def on_screen_resume(self) -> None:
        # refresh counts/order after a quiz, keeping view state
        if hasattr(self, "entries"):
            self.entries = [
                e for e in self.app.client.quiz_dirs() if e["cards_total"] > 0
            ]
            self._rebuild_favorites()
            self._build_tree()

    def _rebuild_favorites(self) -> None:
        query = self.query_one("#filter", Input).value
        ordered = sorted(self.entries, key=lambda e: (-e["runs"], e["path"]))
        if query:
            ordered = fuzzy_filter(query, ordered, key=lambda e: e["path"])
        options = []
        if not query:
            options.append(Option("all cards", id="__all__"))
        for entry in ordered[:30]:
            best = (
                f", best {entry['best']['correct']}/{entry['best']['total']}"
                if entry["best"] else ""
            )
            options.append(Option(
                f"{entry['path']}  ({entry['cards_total']} cards{best})",
                id=entry["path"],
            ))
        option_list = self.query_one("#fav-list", OptionList)
        option_list.clear_options()
        option_list.add_options(options)
        if options:
            option_list.highlighted = 0

    def _build_tree(self) -> None:
        tree = self.query_one("#deck-tree", DeckTree)
        tree.show_root = False
        tree.clear()
        by_path = {e["path"]: e for e in self.entries}

        def children_of(path: str) -> list[dict]:
            prefix = path + "/"
            return sorted(
                (e for e in self.entries
                 if e["path"].startswith(prefix)
                 and "/" not in e["path"][len(prefix):]),
                key=lambda e: e["path"],
            )

        def label(entry: dict) -> str:
            best = (
                f", best {entry['best']['correct']}/{entry['best']['total']}"
                if entry["best"] else ""
            )
            return f"{entry['name']} ({entry['cards_total']} cards{best})"

        def add(parent_node, entry: dict) -> None:
            kids = children_of(entry["path"])
            if kids:
                node = parent_node.add(
                    label(entry), data=entry,
                    expand=entry["path"] in self._memory["expanded"],
                )
                for kid in kids:
                    add(node, kid)
            else:
                parent_node.add_leaf(label(entry), data=entry)

        for top in sorted(
            (e for e in self.entries if "/" not in e["path"]),
            key=lambda e: e["path"],
        ):
            add(tree.root, top)
        unset = by_path  # keep the closure simple for linters
        del unset

    # --- state memory ---------------------------------------------
    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self._memory["tab"] = event.pane.id
        self._focus_active_view()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        if event.node.data:
            self._memory["expanded"].add(event.node.data["path"])

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed) -> None:
        if event.node.data:
            self._memory["expanded"].discard(event.node.data["path"])

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self._memory["filter"] = event.value
            self._rebuild_favorites()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter":
            option_list = self.query_one("#fav-list", OptionList)
            if option_list.option_count:
                self._start(option_list.get_option_at_index(0).id)

    # --- starting a quiz ------------------------------------------
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._start(event.option.id)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.node.data:
            self._start(event.node.data["path"])

    def _start(self, selection: str) -> None:
        path = None if selection == "__all__" else selection

        def launch(n: int | None) -> None:
            if not n:
                return
            client = self.app.client
            dir_id = None
            title = "all cards"
            best = None
            if path is not None:
                title = path
                for entry in self.entries:
                    if entry["path"] == path:
                        dir_id = entry["id"]
                        best = entry["best"]
                        break
            cards = client.quiz_cards(dir_id, recursive=True, n=n)
            if not cards:
                self.notify("No cards found for this selection.", severity="warning")
                return
            self.app.push_screen(QuizScreen(cards, dir_id, title, best))

        self.app.push_screen(CountDialog(), launch)


class CountDialog(ModalScreen[int]):
    """How many questions?"""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="count-dialog"):
            yield Static("How many questions?")
            yield Input(value="20", id="count", type="integer")

    def on_mount(self) -> None:
        self.query_one("#count", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            n = max(1, min(200, int(event.value)))
        except ValueError:
            n = 20
        self.dismiss(n)

    def action_cancel(self) -> None:
        self.dismiss(None)


IMAGE_MD_RE = re.compile(
    r"!\[[^\]]*\]\((https?://[^)\s]+\.(?:png|jpe?g|gif|webp))\)"
)


class QuizScreen(Screen):
    BINDINGS = [Binding("escape", "quit_quiz", "End quiz")]

    def __init__(self, cards: list[dict], dir_id: int | None, title: str, best: dict | None):
        super().__init__()
        self.cards = cards
        self.dir_id = dir_id
        self.deck_title = title
        self.best = best
        self.index = 0
        self.score = 0
        self.answered = 0
        self.wrong_cards: list[dict] = []
        self.run_id: int | None = None
        self.in_feedback = False

    def compose(self) -> ComposeResult:
        with Vertical(id="quiz"):
            yield Static(id="quiz-header")
            yield Markdown(id="question")
            yield Vertical(id="question-image")
            yield Input(placeholder="your answer ...", id="answer")
            yield SelectionList(id="choices")
            yield Button("Submit answer", id="submit", variant="primary")
            yield Static(id="feedback")
            yield Button("Continue", id="continue", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        self.run_id = self.app.client.start_run(self.dir_id, len(self.cards))
        self.show_card()

    def show_card(self) -> None:
        self.in_feedback = False
        card = self.cards[self.index]
        best_text = (
            f"best {self.best['correct']}/{self.best['total']}"
            if self.best else "no best run yet"
        )
        self.query_one("#quiz-header", Static).update(
            f"{self.deck_title} · question {self.index + 1}/{len(self.cards)} "
            f"· score {self.score} · {best_text} · Esc ends the quiz"
        )
        question_md = self._show_images(card["question_md"])
        self.query_one("#question", Markdown).update(question_md)
        answer_input = self.query_one("#answer", Input)
        choices = self.query_one("#choices", SelectionList)
        submit = self.query_one("#submit", Button)
        self.query_one("#feedback", Static).update("")
        self.query_one("#continue", Button).display = False
        if card["type"] == "mc":
            answer_input.display = False
            choices.display = True
            submit.display = True
            choices.clear_options()
            choices.add_options([
                Selection(option["text_md"], option["id"])
                for option in card["options"]
            ])
            choices.focus()
        else:
            choices.display = False
            submit.display = False
            answer_input.display = True
            answer_input.value = ""
            answer_input.focus()

    def _show_images(self, question_md: str) -> str:
        """Render image references as terminal images (kitty/sixel
        with a unicode half-cell fallback); on success the markdown
        image line is dropped from the text. Any failure leaves the
        markdown untouched."""
        holder = self.query_one("#question-image", Vertical)
        holder.remove_children()
        for url in IMAGE_MD_RE.findall(question_md)[:2]:
            try:
                from PIL import Image as PILImage
                from textual_image.widget import Image as ImageWidget

                data = self.app.client.get_bytes(url)
                pil = PILImage.open(io.BytesIO(data))
                pil.load()
                widget = ImageWidget(pil)
                widget.styles.height = 14
                widget.styles.width = "auto"
                holder.mount(widget)
                question_md = IMAGE_MD_RE.sub(
                    lambda m: "" if m.group(1) == url else m.group(0),
                    question_md,
                )
            except Exception:  # noqa: BLE001 - image display is best-effort
                pass
        return question_md

    # --- answering ------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "answer" and not self.in_feedback:
            result = self.app.client.answer(
                self.cards[self.index]["id"], {"answer": event.value}
            )
            self._feedback(result)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit" and not self.in_feedback:
            selected = self.query_one("#choices", SelectionList).selected
            result = self.app.client.answer(
                self.cards[self.index]["id"], {"selected": list(selected)}
            )
            self._feedback(result)
        elif event.button.id == "continue":
            self._next()

    def _feedback(self, result: dict) -> None:
        self.in_feedback = True
        card = self.cards[self.index]
        self.answered += 1
        if result["correct"]:
            self.score += 1
        else:
            self.wrong_cards.append(card)
        expected = result["expected"]
        if result["correct"]:
            if result["match"] == "typo":
                spelling = expected["accepted_answers"][0]
                text = f"✓ correct — typo tolerated, correct spelling: {spelling}"
            else:
                text = "✓ correct"
            self.query_one("#feedback", Static).set_classes("good")
        else:
            if card["type"] == "mc":
                ids = set(expected["correct_option_ids"])
                names = [o["text_md"] for o in card["options"] if o["id"] in ids]
                text = f"✗ wrong — correct: {', '.join(names)}"
            else:
                text = f"✗ wrong — accepted: {', '.join(expected['accepted_answers'])}"
            self.query_one("#feedback", Static).set_classes("bad")
        self.query_one("#feedback", Static).update(text)
        self.query_one("#answer", Input).display = False
        self.query_one("#choices", SelectionList).display = False
        self.query_one("#submit", Button).display = False
        cont = self.query_one("#continue", Button)
        cont.display = True
        cont.focus()

    def _next(self) -> None:
        self.index += 1
        if self.index < len(self.cards):
            self.show_card()
        else:
            self._finish()

    def _finish(self) -> None:
        summary = self.app.client.finish_run(self.run_id, self.score, self.answered)
        self.app.switch_screen(ResultScreen(
            summary, self.cards, self.wrong_cards,
            self.dir_id, self.deck_title, self.best,
        ))

    def action_quit_quiz(self) -> None:
        self.app.client.finish_run(self.run_id, self.score, self.answered)
        self.app.pop_screen()


class ResultScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back to decks")]

    def __init__(self, summary, cards, wrong_cards, dir_id, title, best):
        super().__init__()
        self.summary = summary
        self.cards = cards
        self.wrong_cards = wrong_cards
        self.dir_id = dir_id
        self.deck_title = title
        self.best = best

    def compose(self) -> ComposeResult:
        summary = self.summary
        lines = [
            f"Quiz finished: {self.deck_title}",
            "",
            f"Result: {summary['correct']}/{summary['total']} correct",
            "",
        ]
        top = summary.get("top") or []
        if top:
            lines.append("Top runs:")
            for i, run in enumerate(top, start=1):
                marker = "  ← this run" if summary.get("rank") == i else ""
                lines.append(
                    f"  {i}. {run['correct']}/{run['total']}"
                    f"  ({run['finished_at'][:10]}){marker}"
                )
        with Vertical(id="result"):
            yield Static("\n".join(lines), id="result-text")
            if summary.get("rank") is not None:
                yield Static(TROPHY, id="trophy")
                yield Static(
                    f"New top-{len(top)} run — place #{summary['rank']}!",
                    id="rank-line",
                )
            with Horizontal(id="result-buttons"):
                yield Button("Repeat", id="repeat", variant="primary")
                if self.wrong_cards:
                    yield Button(
                        f"Repeat the {len(self.wrong_cards)} wrong",
                        id="repeat-wrong", variant="warning",
                    )
                yield Button("Done", id="done", variant="success")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "repeat":
            cards = random.sample(self.cards, len(self.cards))
            self.app.switch_screen(
                QuizScreen(cards, self.dir_id, self.deck_title, self.best)
            )
        elif event.button.id == "repeat-wrong":
            cards = random.sample(self.wrong_cards, len(self.wrong_cards))
            self.app.switch_screen(
                QuizScreen(cards, self.dir_id, self.deck_title, self.best)
            )
        else:
            self.app.pop_screen()


class StatsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Static(id="stats-text")
        yield Footer()

    def on_mount(self) -> None:
        client = self.app.client
        data = client.stats()
        summary = data["summary"]
        accuracy = (
            "-" if summary["accuracy"] is None else f"{summary['accuracy']:.0%}"
        )
        lines = [
            "Statistics",
            "",
            f"cards: {summary['cards']} · asked at least once: "
            f"{summary['asked_cards']} · answers: {summary['reviews']} "
            f"· accuracy: {accuracy}",
            "",
        ]
        decks = [d for d in client.quiz_dirs() if d["runs"] > 0][:5]
        if decks:
            lines.append("Top decks (most played):")
            for deck in decks:
                best = (
                    f"best {deck['best']['correct']}/{deck['best']['total']}"
                    if deck["best"] else "no finished run"
                )
                runs = "run" if deck["runs"] == 1 else "runs"
                lines.append(
                    f"  {deck['runs']:>3} {runs}  {deck['path']}"
                    f"  ({deck['cards_total']} cards, {best})"
                )
        else:
            lines.append("No quiz runs yet.")
        self.query_one("#stats-text", Static).update("\n".join(lines))
