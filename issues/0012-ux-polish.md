---
status: in-progress
kind: feature
---

# UX polish batch (TUI)

A batch of usability suggestions gathered while driving the
full-screen TUI. Tracked together; landed incrementally.

1. [x] Exit a task back to the main menu. Escape pops one
   screen; repeating it walks back to home. A follow-up fix
   (CLI 0.15.0): Escape inside a route/quest task used to skip
   to the next card — now task sub-screens dismiss tri-state
   (None = escaped → exit the quiz to the picker; True/False =
   completed → count it and advance).

2. [x] Motivating status info: a correct-answer streak counter
   in the quiz status bar (colored by momentum — dim, cyan at
   3+, bold green at 7+).

3. [x] Tips on request (CLI 0.15.0). The quiz binds `?` to a
   Tip action (shown terse as `? tip`). The answer box is a
   small Input subclass so `?` reaches the screen even while
   typing. A tipped card skips grading entirely — no
   `POST /cards/{id}/answer`, so no review is logged and it is
   not rescheduled — and the status bar shows a `tipped` marker.

4. [x] Local llama as the default LLM, shown in the status bar
   (CLI 0.15.0). A GGUF model runs in-process via llama.cpp, the
   optional `pauk[local]` extra. `pauk.llm.hardware` maps RAM +
   accelerator to a model tier (small curated table, 0.5B–32B
   Q4_K_M; this box → 32B); lazy download into
   `~/.cache/pauk/models/`. `default_provider()` prefers local,
   falls back to the `claude` CLI, then errors. The wrapped
   model id shows in the quiz/quest/route status bars.

5. [x] Show the tree (deck hierarchy) view by default in the
   picker; Tab toggles to the favorites/filter view.

6. [x] Color pass: typo-tolerant answers amber, quest chat
   speakers colored (you = cyan, partner = green), route
   semantics (current node cyan, goal yellow, arrival green,
   record gold), per-type glyphs, red→amber→green deck
   performance badges.

7. [ ] Training mode: questions in a left column, input in the
   center, answers on the right; reveal toggleable by a key
   (current question or all at once).

8. [~] Speed. Load-up and LLM interactions are slow.
   Decision: keep IONOS, add client-side caching + connection
   prewarm (no hosting migration, no SQLite sync).

   Done (CLI 0.14.0):
   - Local stale-while-revalidate cache (`cli/pauk/cache.py`) for
     the read-heavy GETs the picker/quiz/stats repeat (`/quiz/dirs`,
     `/dirs`, `/quiz/cards`, `/stats`): a hit returns the last
     payload instantly and a stale entry refreshes in the
     background. One small JSON file per entry under
     `~/.cache/pauk/` (honours `XDG_CACHE_HOME`), keyed by a hash of
     server URL + token so servers/users never cross-contaminate.
     TTLs 15–60 s; every write busts the cache (a started run only
     busts `/quiz/dirs`, keeping the card batch warm for the quiz it
     precedes). Escape hatches: `--no-cache`, `PAUK_NO_CACHE`,
     `pauk cache clear`.
   - Connection keep-alive: the httpx client now holds the TLS
     connection open (60 s expiry, up from httpx's 5 s default) so
     the first quiz reuses it instead of a cold handshake.
   - Prewarm: `run_tui` fires `health` + `quiz_dirs` in the
     background before the UI starts, so the picker paints from a
     warm connection and a primed cache.

   LLM latency: the local provider streams internally; token-by-token
   streaming into the TUI is deferred (worker-thread render rework).

9. Windows recipe + maps fallback/passthrough docs + journey
   feature + upload:
   - [x] Upload + clone (`pauk upload` / `pauk clone`).
   - [x] Reliable image fallback: `auto` mode drops to the
     half-block renderer under tmux; configurable via
     `image_mode` / `PAUK_IMAGE_MODE` / `tmux_image_passthrough`.
     Passthrough setup documented in `docs/images.md`. `pauk
     doctor` reports terminal image support + the chosen renderer.
   - [x] Windows recipe: pauk installs cross-platform via pipx
     from the now-public GitHub repo (toscpm 1.27.0).
   - [ ] Journey feature — needs a data-model design pass.
