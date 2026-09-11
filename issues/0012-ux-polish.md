---
status: open
kind: feature
---

# UX polish batch (TUI)

A batch of usability suggestions gathered while driving the
full-screen TUI. Tracked together; landed incrementally.

1. [x] Exit a task back to the main menu. Escape pops one
   screen; repeating it walks back to home. (No extra key added
   — Escape is universally understood and already chains.)

2. [x] Motivating status info: a correct-answer streak counter
   in the quiz status bar (colored by momentum — dim, cyan at
   3+, bold green at 7+).

3. [ ] Tips on request: an LLM-generated hint on a key. A
   tipped question logs no review (neither right nor wrong).
   Blocked on the LLM provider decision.

4. [ ] Show the currently available LLM in the status bar.
   (Partial; depends on the LLM transport decision.)

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

8. [ ] Speed. Load-up and LLM interactions are slow.
   Investigation done (see below); implementation pending user
   decisions: local stale-while-revalidate cache + connection
   prewarm + LLM streaming; keep IONOS; advise against
   SQLite-over-GitHub sync.

9. Windows recipe + maps fallback/passthrough docs + journey
   feature + upload:
   - [x] Upload + clone (`pauk upload` / `pauk clone`).
   - [x] Reliable image fallback: `auto` mode drops to the
     half-block renderer under tmux; configurable via
     `image_mode` / `PAUK_IMAGE_MODE` / `tmux_image_passthrough`.
     Passthrough setup documented in `docs/images.md`.
   - [ ] Windows recipe — blocked on a design decision: toscpm
     runs recipes through cmd.exe (`shell=True`), and has no
     path that runs a shell/PowerShell script on Windows at all
     (Windows no-admin installs go through in-process PyStep or
     winget). So the drafted PowerShell recipe cannot run.
     Options: (a) in-process PyStep recipe, (b) document WSL.
   - [ ] Journey feature — needs a data-model design pass.
