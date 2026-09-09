---
status: in-progress
kind: task
---

# Overnight continuous-improvement loop

Roadmap for the review → fix → next-issue loop (API + CLI only).

Done:

- Iteration 1: match card type (pronoun→form mappings) end to
  end (API 0.5.0, migration 004); +180 content cards (Italian
  present-tense conjugations, German match/facts). Review fixes:
  quit-early runs unranked, image prefetch, answer/finish in
  worker threads, httpx close, migration comment safety. UI
  minimalism pass on all status bars.

Remaining, in priority order:

1. DONE — LLM provider + hardware model selection + quest card
   type (issues/0009). Local llama runtime still to wire.
   Detect RAM + CPU/GPU, pick a default model tier; prefer the
   `claude` CLI when present, else a llama.cpp GGUF sized to the
   machine. M2/32GB → larger model than 16GB/no-GPU.

2. Quests / tasks card type: a scenario solved by dialog with
   the chosen LLM, deterministically scored (message count,
   success criteria). Highscores via quiz_runs-style tracking.

3. Map encoding for route/annotation tasks: build on
   content/autobahn-graph.json + scripts/maps/render_route.py.
   "Drive Munich→Berlin" as a quest; annotate-city/autobahn as
   match/mc for pleasantness.

4. Printable architecture book (issues/0011): DB schema, IONOS
   deployment, tables/columns/types, example questions/tasks,
   CLI "screenshots", curl API examples.

5. Every round: deep UI-minimalism review; ruthless trimming.

2026-09-09 (iteration 4): map-encoded route tasks shipped
(API 0.7.0 / CLI 0.10.0). route card type, bundled autobahn
graph, deterministic km, Pillow route map, TUI RouteScreen.
Only the printable book (issues/0011) remains.
