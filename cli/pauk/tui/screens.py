"""Screens of the pauk TUI: Home → Picker → Quiz → Result.

Network calls run in background threads (Textual @work) so the UI
never blocks: every screen paints immediately with a "Loading…"
line and fills in when the data arrives. One status bar per
screen (position from settings); no separate header.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Markdown, OptionList, SelectionList, Static, Tree
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

from pauk import config as config_mod
from pauk.fuzzy import fuzzy_filter

ASSETS = Path(__file__).parent / "assets"

LOGO = r"""
  _ __   __ _ _   _ _  __
 | '_ \ / _` | | | | |/ /
 | |_) | (_| | |_| |   <
 | .__/ \__,_|\__,_|_|\_\
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


class StatusBar(Static):
    """One status line, docked top or bottom per the user's
    setting. Multi-line content is fine."""

    def on_mount(self) -> None:
        position = config_mod.get("statusbar_position")
        self.styles.dock = "top" if position == "top" else "bottom"


class HomeScreen(Screen):
    BINDINGS = [Binding("q", "app.quit", "Quit")]

    def compose(self) -> ComposeResult:
        with Vertical(id="home"):
            yield Static(LOGO, id="logo")
            yield Static("the flashcard trainer", id="tagline")
            yield OptionList(
                Option("Start a quiz", id="quiz"),
                Option("Statistics", id="stats"),
                Option("Settings", id="settings"),
                Option("Quit", id="quit"),
                id="home-menu",
            )
        yield StatusBar("")

    def on_mount(self) -> None:
        menu = self.query_one("#home-menu", OptionList)
        menu.highlighted = 0
        menu.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == "quiz":
            self.app.push_screen(PickerScreen())
        elif event.option.id == "stats":
            self.app.push_screen(StatsScreen())
        elif event.option.id == "settings":
            self.app.push_screen(SettingsScreen())
        else:
            self.app.exit()


class DeckTree(Tree):
    """Right enters a directory, Left leaves it (or jumps to the
    parent)."""

    BINDINGS = [
        Binding("right", "enter_dir", "Enter", show=True),
        Binding("left", "leave_dir", "Leave", show=True),
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
    """Deck selection with a favorites list and a directory tree.
    View/expansion/filter state and the chosen question count live
    on the app, so they survive leaving and re-entering."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("f2", "toggle_view", "Fav/Tree"),
    ]

    entries: list[dict] = []

    @property
    def _memory(self) -> dict:
        app = self.app
        if not hasattr(app, "picker_memory"):
            app.picker_memory = {
                "view": "fav",
                "expanded": set(),
                "filter": "",
                "n": config_mod.get("default_questions"),
            }
        return app.picker_memory

    def compose(self) -> ComposeResult:
        yield OptionList(id="fav-list")
        yield DeckTree("decks", id="deck-tree")
        yield StatusBar("Loading…", id="picker-status")

    def on_mount(self) -> None:
        # data is fetched in on_screen_resume (which also fires on
        # first show), so the payload is loaded exactly once per visit
        self._apply_view()

    def on_screen_resume(self) -> None:
        self._update_status()
        self._load_decks()

    @work(exclusive=True, thread=True)
    def _load_decks(self) -> None:
        try:
            data = self.app.client.quiz_dirs()
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.notify, f"Could not load decks: {exc}", severity="error"
            )
            return
        self.app.call_from_thread(self._populate, data)

    def _populate(self, data: list[dict]) -> None:
        self.entries = [e for e in data if e["cards_total"] > 0]
        self._rebuild_favorites()
        self._build_tree()

    # --- input ----------------------------------------------------
    def on_key(self, event) -> None:
        # handled here rather than via bindings so that bracket keys
        # and typed filter characters both reach the screen (a
        # focused Input would swallow them); arrows/enter/tab are
        # left for the focused list or tree
        if event.key == "right_square_bracket":
            self.action_more_questions(); event.stop(); return
        if event.key == "left_square_bracket":
            self.action_fewer_questions(); event.stop(); return
        if self._memory["view"] != "fav":
            return
        if event.key == "backspace":
            self._memory["filter"] = self._memory["filter"][:-1]
            self._rebuild_favorites(); self._update_status(); event.stop()
        elif event.is_printable and event.character:
            self._memory["filter"] += event.character
            self._rebuild_favorites(); self._update_status(); event.stop()

    # --- views ----------------------------------------------------
    def _apply_view(self) -> None:
        tree_view = self._memory["view"] == "tree"
        self.query_one("#deck-tree").display = tree_view
        self.query_one("#fav-list").display = not tree_view
        if tree_view:
            self.query_one("#deck-tree", DeckTree).focus()
        else:
            self.query_one("#fav-list", OptionList).focus()

    def action_toggle_view(self) -> None:
        self._memory["view"] = "tree" if self._memory["view"] == "fav" else "fav"
        self._apply_view()
        self._update_status()

    def action_more_questions(self) -> None:
        self._memory["n"] = min(200, self._memory["n"] + 5)
        self._update_status()

    def action_fewer_questions(self) -> None:
        self._memory["n"] = max(1, self._memory["n"] - 5)
        self._update_status()

    def _update_status(self) -> None:
        n = self._memory["n"]
        if self._memory["view"] == "tree":
            self.query_one("#picker-status", StatusBar).update(
                f"{n} questions · [ ] · Tab list"
            )
        else:
            flt = self._memory["filter"]
            typed = f" · /{flt}" if flt else ""
            self.query_one("#picker-status", StatusBar).update(
                f"{n} questions · [ ] · Tab tree{typed}"
            )

    def _rebuild_favorites(self) -> None:
        query = self._memory["filter"]
        ordered = sorted(self.entries, key=lambda e: (-e["runs"], e["path"]))
        if query:
            ordered = fuzzy_filter(query, ordered, key=lambda e: e["path"])
        options = []
        if not query:
            options.append(Option("all cards", id="__all__"))
        for entry in ordered[:30]:
            options.append(Option(f"{entry['path']}  {_best_tag(entry)}", id=entry["path"]))
        option_list = self.query_one("#fav-list", OptionList)
        option_list.clear_options()
        option_list.add_options(options)
        if options:
            option_list.highlighted = 0

    def _build_tree(self) -> None:
        tree = self.query_one("#deck-tree", DeckTree)
        tree.show_root = False
        tree.clear()

        def children_of(path: str) -> list[dict]:
            prefix = path + "/"
            return sorted(
                (e for e in self.entries
                 if e["path"].startswith(prefix)
                 and "/" not in e["path"][len(prefix):]),
                key=lambda e: e["path"],
            )

        def add(parent_node, entry: dict) -> None:
            label = f"{entry['name']}  ({entry['cards_total']} cards) {_best_tag(entry)}"
            kids = children_of(entry["path"])
            if kids:
                node = parent_node.add(
                    label, data=entry, expand=entry["path"] in self._memory["expanded"]
                )
                for kid in kids:
                    add(node, kid)
            else:
                parent_node.add_leaf(label, data=entry)

        for top in sorted(
            (e for e in self.entries if "/" not in e["path"]), key=lambda e: e["path"]
        ):
            add(tree.root, top)

    # --- state memory ---------------------------------------------
    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        if event.node.data:
            self._memory["expanded"].add(event.node.data["path"])

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed) -> None:
        if event.node.data:
            self._memory["expanded"].discard(event.node.data["path"])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._start(event.option.id)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.node.data:
            self._start(event.node.data["path"])

    def _start(self, selection: str) -> None:
        path = None if selection == "__all__" else selection
        dir_id = None
        title = "all cards"
        if path is not None:
            title = path
            for entry in self.entries:
                if entry["path"] == path:
                    dir_id = entry["id"]
                    break
        self.app.push_screen(QuizScreen(dir_id, title, self._memory["n"]))


def _best_tag(entry: dict) -> str:
    if entry.get("best"):
        return f"· best {round(entry['best']['accuracy'] * 100)}%"
    return ""


IMAGE_MD_RE = re.compile(
    r"!\[[^\]]*\]\((https?://[^)\s]+\.(?:png|jpe?g|gif|webp))\)"
)


class QuizScreen(Screen):
    """A quiz session. Cards are fetched in the background; the
    screen paints immediately."""

    BINDINGS = [
        Binding("escape", "quit_quiz", "End quiz"),
        Binding("enter", "advance", "Continue", show=False),
    ]

    def __init__(self, dir_id: int | None, title: str, n: int, ranked: bool = True,
                 cards: list[dict] | None = None):
        super().__init__()
        self.dir_id = dir_id
        self.deck_title = title
        self.n = n
        self.ranked = ranked
        self.preset_cards = cards
        self.cards: list[dict] = []
        self.index = 0
        self.score = 0
        self.answered = 0
        self.wrong_cards: list[dict] = []
        self.run_id: int | None = None
        self.best = None
        self.in_feedback = False

    def compose(self) -> ComposeResult:
        with Vertical(id="quiz"):
            yield Markdown(id="question")
            yield Vertical(id="question-image")
            yield Static("", id="match-left")
            yield OptionList(id="match-choices")
            yield Input(placeholder="answer", id="answer")
            yield SelectionList(id="choices")
            with Horizontal(id="quiz-buttons", classes="compact-buttons"):
                yield Button("Submit", id="submit")
                yield Button("Continue", id="continue")
            yield Static("", id="feedback")
        yield StatusBar("Loading…", id="quiz-status")

    def on_mount(self) -> None:
        self._begin()

    @work(exclusive=True, thread=True)
    def _begin(self) -> None:
        try:
            cards = self.preset_cards
            if cards is None:
                cards = self.app.client.quiz_cards(self.dir_id, True, self.n)
            if not cards:
                self.app.call_from_thread(
                    self.notify, "No cards for this selection.", severity="warning"
                )
                self.app.call_from_thread(self.app.pop_screen)
                return
            run = self.app.client.start_run(self.dir_id, len(cards), self.ranked)
            # warm the image cache up front so no card paint blocks on
            # a download later
            for card in cards:
                for url in IMAGE_MD_RE.findall(card["question_md"]):
                    try:
                        self.app.image_for(url)
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.notify, f"Could not start quiz: {exc}", severity="error"
            )
            self.app.call_from_thread(self.app.pop_screen)
            return
        self.cards = cards
        self.run_id = run["id"]
        self.best = run.get("best")
        self.app.call_from_thread(self.show_card)

    def _status(self) -> None:
        best = f" · best {round(self.best['accuracy'] * 100)}%" if self.best else ""
        self.query_one("#quiz-status", StatusBar).update(
            f"Q {self.index + 1}/{len(self.cards)} · score {self.score}{best}"
        )

    def show_card(self) -> None:
        self.in_feedback = False
        card = self.cards[self.index]
        if card["type"] == "quest":
            # a quest is played in its own screen; the outcome counts
            # as one item of this quiz
            self.app.push_screen(QuestScreen(card), self._quest_done)
            return
        if card["type"] == "route":
            self.app.push_screen(RouteScreen(card), self._quest_done)
            return
        self._status()
        question_md = self._show_images(card["question_md"])
        self.query_one("#question", Markdown).update(question_md)
        self.query_one("#feedback", Static).update("")
        self.query_one("#continue", Button).display = False
        # hide every answer widget, then show the ones this type needs
        for wid in ("#answer", "#choices", "#submit", "#match-left", "#match-choices"):
            self.query_one(wid).display = False

        if card["type"] == "mc":
            choices = self.query_one("#choices", SelectionList)
            choices.display = True
            self.query_one("#submit", Button).display = True
            choices.clear_options()
            choices.add_options([Selection(o["text_md"], o["id"]) for o in card["options"]])
            choices.focus()
        elif card["type"] == "match":
            self._match_idx = 0
            self._match_answers = {}
            self.query_one("#match-left").display = True
            self.query_one("#match-choices").display = True
            self._show_match_left()
        else:
            answer = self.query_one("#answer", Input)
            answer.display = True
            answer.value = ""
            answer.focus()

    def _show_match_left(self) -> None:
        card = self.cards[self.index]
        left = card["lefts"][self._match_idx]
        self.query_one("#match-left", Static).update(
            f"[{self._match_idx + 1}/{len(card['lefts'])}]  {left['left_md']}  →"
        )
        choices = self.query_one("#match-choices", OptionList)
        choices.clear_options()
        choices.add_options([
            Option(c["right_md"], id=str(c["id"])) for c in card["choices"]
        ])
        choices.highlighted = 0
        choices.focus()

    def _show_images(self, question_md: str) -> str:
        holder = self.query_one("#question-image", Vertical)
        holder.remove_children()
        for url in IMAGE_MD_RE.findall(question_md)[:2]:
            try:
                from textual_image.widget import Image as ImageWidget

                pil = self.app.image_for(url)
                widget = ImageWidget(pil)
                widget.styles.height = 14
                widget.styles.width = "auto"
                holder.mount(widget)
                question_md = IMAGE_MD_RE.sub(
                    lambda m: "" if m.group(1) == url else m.group(0), question_md
                )
            except Exception:  # noqa: BLE001 - image display is best-effort
                pass
        return question_md

    # --- answering ------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "answer" and not self.in_feedback:
            self._grade({"answer": event.value})

    def action_advance(self) -> None:
        if self.in_feedback:
            self._next()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit" and not self.in_feedback:
            selected = list(self.query_one("#choices", SelectionList).selected)
            self._grade({"selected": selected})
        elif event.button.id == "continue":
            self._next()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self.in_feedback or self.cards[self.index]["type"] != "match":
            return
        card = self.cards[self.index]
        left_id = card["lefts"][self._match_idx]["id"]
        self._match_answers[str(left_id)] = int(event.option.id)
        self._match_idx += 1
        if self._match_idx < len(card["lefts"]):
            self._show_match_left()
        else:
            self._grade({"matches": self._match_answers})

    @work(thread=True)
    def _grade(self, payload: dict) -> None:
        try:
            result = self.app.client.answer(self.cards[self.index]["id"], payload)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.notify, f"Could not submit answer: {exc}", severity="error"
            )
            return
        self.app.call_from_thread(self._feedback, result)

    def _feedback(self, result: dict) -> None:
        self.in_feedback = True
        card = self.cards[self.index]
        self.answered += 1
        if result["correct"]:
            self.score += 1
        else:
            self.wrong_cards.append(card)
        expected = result["expected"]
        feedback = self.query_one("#feedback", Static)
        if result["correct"]:
            if result["match"] == "typo":
                text = f"✓ correct — typo tolerated, correct spelling: {expected['accepted_answers'][0]}"
            else:
                text = "✓ correct"
            feedback.set_classes("good")
        else:
            if card["type"] == "mc":
                ids = set(expected["correct_option_ids"])
                names = [o["text_md"] for o in card["options"] if o["id"] in ids]
                text = f"✗ wrong — correct: {', '.join(names)}"
            elif card["type"] == "match":
                pairs = ", ".join(
                    f"{p['left_md']}→{p['right_md']}" for p in expected["pairs"]
                )
                text = f"✗ wrong — {pairs}"
            else:
                text = f"✗ wrong — accepted: {', '.join(expected['accepted_answers'])}"
            feedback.set_classes("bad")
        feedback.update(text)
        for wid in ("#answer", "#choices", "#submit", "#match-left", "#match-choices"):
            self.query_one(wid).display = False
        cont = self.query_one("#continue", Button)
        cont.display = True
        cont.focus()

    def _quest_done(self, success: bool | None) -> None:
        # returning from a quest: count it, then move on
        card = self.cards[self.index]
        self.answered += 1
        if success:
            self.score += 1
        else:
            self.wrong_cards.append(card)
        self._next()

    def _next(self) -> None:
        self.index += 1
        if self.index < len(self.cards):
            self.show_card()
        else:
            self._finish()

    @work(thread=True)
    def _finish(self) -> None:
        try:
            summary = self.app.client.finish_run(self.run_id, self.score, self.answered)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.notify, f"Could not save result: {exc}", severity="error"
            )
            self.app.call_from_thread(self.app.pop_screen)
            return
        self.app.call_from_thread(self._show_result, summary)

    def _show_result(self, summary: dict) -> None:
        self.app.switch_screen(ResultScreen(
            summary, self.cards, self.wrong_cards, self.dir_id, self.deck_title, self.n
        ))

    def action_quit_quiz(self) -> None:
        # an abandoned run is finished as unranked so a partial score
        # never enters a per-n leaderboard
        if self.run_id is not None:
            try:
                self.app.client.finish_run(
                    self.run_id, self.score, self.answered, ranked=False
                )
            except Exception:  # noqa: BLE001 - leaving anyway
                pass
        self.app.pop_screen()


class ResultScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("r", "repeat", "Repeat"),
        Binding("w", "repeat_wrong", "Repeat wrong"),
    ]

    def __init__(self, summary, cards, wrong_cards, dir_id, title, n):
        super().__init__()
        self.summary = summary
        self.cards = cards
        self.wrong_cards = wrong_cards
        self.dir_id = dir_id
        self.deck_title = title
        self.n = n

    def compose(self) -> ComposeResult:
        summary = self.summary
        pct = round(summary["correct"] / summary["total"] * 100) if summary["total"] else 0
        lines = [
            f"Quiz finished: {self.deck_title}",
            "",
            f"Result: {summary['correct']}/{summary['total']} correct ({pct}%)",
        ]
        top = summary.get("top") or []
        if top:
            lines.append("")
            lines.append(f"Top runs for n={self.n}:")
            for i, run in enumerate(top, start=1):
                marker = "  ← this run" if summary.get("rank") == i else ""
                lines.append(
                    f"  {i}. {round(run['accuracy'] * 100)}%  "
                    f"({run['correct']}/{run['total']}, {run['finished_at'][:10]}){marker}"
                )
        with Vertical(id="result"):
            if summary.get("rank") is not None:
                yield self._trophy()
                yield Static(f"New record — #{summary['rank']}!", id="rank-line")
            yield Static("\n".join(lines), id="result-text")
            with Horizontal(id="result-buttons", classes="compact-buttons"):
                yield Button("Repeat", id="repeat")
                if self.wrong_cards:
                    yield Button(f"Repeat {len(self.wrong_cards)} wrong", id="repeat-wrong")
                yield Button("Done", id="done")
        yield StatusBar("r repeat · w wrong")

    def _trophy(self):
        try:
            from PIL import Image as PILImage
            from textual_image.widget import Image as ImageWidget

            widget = ImageWidget(PILImage.open(ASSETS / "trophy.png"))
            widget.styles.height = 12
            widget.styles.width = "auto"
            return widget
        except Exception:  # noqa: BLE001 - ascii fallback
            return Static(TROPHY, id="trophy")

    def action_repeat(self) -> None:
        self._repeat(self.cards)

    def action_repeat_wrong(self) -> None:
        if self.wrong_cards:
            self._repeat(self.wrong_cards)

    def _repeat(self, cards: list[dict]) -> None:
        # repeats are practice, not ranked — a 1/1 repeat-wrong must
        # never become a "best run"
        shuffled = random.sample(cards, len(cards))
        self.app.switch_screen(
            QuizScreen(self.dir_id, self.deck_title, len(shuffled),
                       ranked=False, cards=shuffled)
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "repeat":
            self.action_repeat()
        elif event.button.id == "repeat-wrong":
            self.action_repeat_wrong()
        else:
            self.app.pop_screen()


class QuestScreen(Screen):
    """Play one quest: a dialog with the LLM in character, then a
    judged success and the fewest-messages highscore. Dismisses with
    the success boolean so the surrounding quiz can count it."""

    BINDINGS = [
        Binding("escape", "give_up", "Give up"),
        Binding("f2", "finish", "Finish", show=True),
    ]

    def __init__(self, card: dict):
        super().__init__()
        self.card = card
        self.messages: list[dict] = []
        self.user_messages = 0
        self.finished = False

    def compose(self) -> ComposeResult:
        with Vertical(id="quest"):
            yield Markdown(self.card["scenario_md"], id="quest-scenario")
            yield Static("", id="quest-log")
            yield Input(placeholder="your message", id="quest-input")
        yield StatusBar("", id="quest-status")

    def on_mount(self) -> None:
        self._update_status()
        self.query_one("#quest-input", Input).focus()

    def _update_status(self) -> None:
        maxm = self.card["max_messages"]
        lang = f" · {self.card['lang']}" if self.card.get("lang") else ""
        self.query_one("#quest-status", StatusBar).update(
            f"message {self.user_messages}/{maxm}{lang} · F2 finish"
        )

    def _render_log(self) -> None:
        lines = []
        for m in self.messages:
            who = "you" if m["role"] == "user" else "•"
            lines.append(f"{who}: {m['content']}")
        self.query_one("#quest-log", Static).update("\n\n".join(lines))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.finished or event.input.id != "quest-input":
            return
        text = event.value.strip()
        if not text:
            return
        self.messages.append({"role": "user", "content": text})
        self.user_messages += 1
        event.input.value = ""
        self._render_log()
        self._update_status()
        self._reply()

    @work(thread=True)
    def _reply(self) -> None:
        try:
            reply = self.app.provider.chat(self.card["role_prompt"], self.messages)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.notify, f"LLM error: {exc}", severity="error"
            )
            return
        self.app.call_from_thread(self._got_reply, reply)

    def _got_reply(self, reply: str) -> None:
        self.messages.append({"role": "assistant", "content": reply})
        self._render_log()
        if self.user_messages >= self.card["max_messages"]:
            self.action_finish()

    def action_finish(self) -> None:
        if self.finished or not self.messages:
            if not self.messages:
                self.dismiss(False)
            return
        self.finished = True
        self.query_one("#quest-input", Input).disabled = True
        self.query_one("#quest-status", StatusBar).update("judging…")
        self._judge()

    @work(thread=True)
    def _judge(self) -> None:
        try:
            success = self.app.provider.judge(self.card["success_criteria"], self.messages)
            result = self.app.client.quest_run(self.card["id"], success, self.user_messages)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.notify, f"Could not finish quest: {exc}", severity="error"
            )
            self.app.call_from_thread(self.dismiss, False)
            return
        self.app.call_from_thread(self._show_outcome, success, result)

    def _show_outcome(self, success: bool, result: dict) -> None:
        best = result.get("best_messages")
        verdict = "✓ succeeded" if success else "✗ not this time"
        extra = ""
        if success and result.get("rank"):
            extra = f" · best {best} messages (#{result['rank']})"
        self.query_one("#quest-log", Static).update(
            (str(self.query_one("#quest-log", Static).render()) + "\n\n")
            + f"{verdict} in {self.user_messages} messages{extra}"
        )
        self.query_one("#quest-status", StatusBar).update("done")
        self._pending_success = success
        self.set_focus(None)

    def action_give_up(self) -> None:
        # Esc after the outcome continues; Esc mid-quest gives up
        if getattr(self, "_pending_success", None) is not None:
            self.dismiss(self._pending_success)
        else:
            self.dismiss(False)


class RouteScreen(Screen):
    """Navigate a graph from start to goal by picking edges (multiple
    choice). Kilometres are summed from the bundled graph; on arrival
    the route is recorded (fewest-km highscore). Dismisses with the
    success flag so the surrounding quiz can count it."""

    BINDINGS = [Binding("escape", "leave", "Give up")]

    def __init__(self, card: dict):
        super().__init__()
        self.card = card
        self.graph = None
        self.node_path: list[str] = []
        self.km = 0
        self.done = False
        self.arrived = False
        self.current_moves: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="route"):
            yield Static("", id="route-here")
            yield OptionList(id="route-moves")
            yield Static("", id="route-outcome")
        yield StatusBar("route", id="route-status")

    def on_mount(self) -> None:
        from pauk.route import load_graph

        try:
            self.graph = load_graph(self.card["graph_name"])
        except Exception:  # noqa: BLE001
            self.notify("Route graph not available.", severity="error")
            self.dismiss(False)
            return
        self.node_path = [self.card["start_node"]]
        self._refresh_moves()

    def _refresh_moves(self) -> None:
        node = self.node_path[-1]
        self.query_one("#route-here", Static).update(
            f"You are in {self.graph.name_of(node)}  "
            f"(goal: {self.graph.name_of(self.card['goal_node'])})"
        )
        self.query_one("#route-status", StatusBar).update(f"{self.km} km so far")
        self.current_moves = self.graph.moves(node)
        moves = self.query_one("#route-moves", OptionList)
        moves.clear_options()
        moves.add_options([
            Option(f"{m['autobahn']} → {self.graph.name_of(m['to'])}  ({m['km']} km)")
            for m in self.current_moves
        ])
        if self.current_moves:
            moves.highlighted = 0
        moves.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self.done:
            return
        move = self.current_moves[event.option_index]
        self.node_path.append(move["to"])
        self.km += int(move["km"])
        if move["to"] == self.card["goal_node"]:
            self._arrive()
        else:
            self._refresh_moves()

    def _arrive(self) -> None:
        self.done = True
        self.arrived = True
        self.query_one("#route-moves", OptionList).display = False
        self._show_map()
        self._record()

    def _show_map(self) -> None:
        if getattr(self.app, "is_headless", False):
            return
        try:
            import io

            from PIL import Image as PILImage
            from textual_image.widget import Image as ImageWidget

            from pauk.route import render_route_png

            png = render_route_png(self.graph, self.node_path)
            widget = ImageWidget(PILImage.open(io.BytesIO(png)))
            widget.styles.height = 18
            widget.styles.width = "auto"
            self.mount(widget)
        except Exception:  # noqa: BLE001 - map is best-effort
            pass

    @work(thread=True)
    def _record(self) -> None:
        try:
            result = self.app.client.route_run(self.card["id"], True, self.km)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.notify, f"Could not save route: {exc}", severity="error"
            )
            return
        self.app.call_from_thread(self._outcome, result)

    def _outcome(self, result: dict) -> None:
        best = result.get("best_km")
        extra = f" · best {best} km" if best is not None else ""
        record = " — new record!" if result.get("rank") == 1 else ""
        self.query_one("#route-outcome", Static).update(
            f"Arrived in {self.km} km{extra}{record}"
        )
        self.query_one("#route-status", StatusBar).update("done")

    def action_leave(self) -> None:
        self.dismiss(self.arrived)


class StatsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Static("Loading…", id="stats-text")
        yield StatusBar("")

    def on_mount(self) -> None:
        self._load()

    @work(exclusive=True, thread=True)
    def _load(self) -> None:
        try:
            data = self.app.client.stats()
            decks = self.app.client.quiz_dirs()
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.notify, f"Could not load stats: {exc}", severity="error"
            )
            return
        self.app.call_from_thread(self._render_stats, data, decks)

    def _render_stats(self, data: dict, decks: list[dict]) -> None:
        summary = data["summary"]
        accuracy = "-" if summary["accuracy"] is None else f"{summary['accuracy']:.0%}"
        lines = [
            "Statistics",
            "",
            f"cards: {summary['cards']} · asked at least once: {summary['asked_cards']} "
            f"· answers: {summary['reviews']} · accuracy: {accuracy}",
            "",
        ]
        top = [d for d in decks if d["runs"] > 0][:5]
        if top:
            lines.append("Top decks (most played):")
            for deck in top:
                best = (
                    f"best {round(deck['best']['accuracy'] * 100)}%"
                    if deck["best"] else "no ranked run"
                )
                runs = "run" if deck["runs"] == 1 else "runs"
                lines.append(
                    f"  {deck['runs']:>3} {runs}  {deck['path']}  "
                    f"({deck['cards_total']} cards, {best})"
                )
        else:
            lines.append("No quiz runs yet.")
        self.query_one("#stats-text", Static).update("\n".join(lines))


class SettingsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        with Vertical(id="settings"):
            yield Static("Settings", id="settings-title")
            yield Static("Status bar position:")
            yield OptionList(
                Option("bottom", id="bottom"),
                Option("top", id="top"),
                id="pos-list",
            )
            yield Static("Default questions per quiz:")
            yield Input(
                value=str(config_mod.get("default_questions")),
                id="default-n", type="integer",
            )
        yield StatusBar("")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        config_mod.set_value("statusbar_position", event.option.id)
        self.notify(f"Status bar: {event.option.id} (applies on next screen)")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "default-n":
            try:
                n = max(1, min(200, int(event.value)))
            except ValueError:
                n = 25
            config_mod.set_value("default_questions", n)
            self.notify(f"Default questions: {n}")
