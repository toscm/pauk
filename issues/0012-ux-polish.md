---
status: in-progress
kind: feature
---

# UX polish

A basket of small quiz/TUI refinements.
Items are tracked individually below.

## Item 3 — tips on request

Let the learner ask for a hint on the current question.

The LLM (the app's quest/tip provider) generates a one-line hint that nudges toward the answer without revealing it.
A question for which a tip was requested counts as NEITHER right nor wrong: it logs NO review to the API and is not scheduled to resurface.
The status bar shows a `tipped` marker once a hint has been requested for the current card.

2026-09-11 (CLI 0.13.0): done.
The quiz binds `?` to a Tip action (shown terse as `? tip` in the status bar, since `?` is not a universal key).
Because a focused answer `Input` otherwise swallows every printable key — even a priority screen binding — the answer box is a small `Input` subclass (`QuizInput`) that lets `?` through to the screen.
Requesting a tip marks the card `tipped`; submitting a tipped card skips grading entirely (no `POST /cards/{id}/answer`, so no review is logged) and advances with a neutral "tipped — not scored" outcome.

## Item 4 — local llama as the default LLM, shown in the status bar

Run a language model locally by default instead of depending on the `claude` CLI, and show which model is answering.

The model quality is chosen automatically from the machine's hardware (RAM, cores, GPU/Metal).
The chosen model id appears in the quiz, quest, and route status bars (or `claude-cli` when falling back).

2026-09-11 (CLI 0.13.0): done.
A local GGUF model runs in-process via llama.cpp, packaged as the optional `pauk[local]` extra (lazily imported, no always-on daemon).
`pauk.llm.hardware` detects RAM, logical cores, and accelerator, and maps RAM+accelerator to a model tier from a small curated table (0.5B → 32B, Q4_K_M); cores set the llama.cpp thread count (capped at 16).
The model is downloaded lazily on first use into `~/.cache/pauk/models/` (respects `XDG_CACHE_HOME`); `PAUK_NO_MODEL_DOWNLOAD` hard-blocks downloads and tests mock the provider, so nothing is ever fetched in CI.
`default_provider()` prefers the local runtime when installed, falls back to the `claude` CLI, then raises a clear "no LLM available" error.
The status bar shows the wrapped model id via `provider.name` (the model key for local models, `claude-cli` on fallback).

## Item (folded in) — Escape inside a task exits the quiz

Pressing Escape inside a route/quest task skipped to the next card instead of leaving the quiz.

2026-09-11 (CLI 0.13.0): fixed.
Task sub-screens now dismiss with a tri-state value: `None` when the user escapes/gives up (the quiz exits back to the picker), `True`/`False` when the task completes (the item is counted and the quiz advances).
