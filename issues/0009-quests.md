---
status: open
kind: feature
---

# Quests (LLM-driven dialog tasks)

A new card/item type `quest`: a scenario the user solves by
dialog with an LLM playing a role, judged for success. Two
examples driving the design:

- Language: "order 2 croissants and 1 coffee from an Italian
  baker who speaks only Italian, in <= 10 messages."

- Geography: "drive from München to Berlin using as few km as
  possible" — the LLM parses each step ("we take the A9 to
  Leipzig") into graph edges; pauk colors the route on the map
  and sums km deterministically (content/autobahn-graph.json +
  scripts/maps/render_route.py already exist).

Design principles:

- Keep scoring deterministic where possible. The LLM does
  roleplay and free-text parsing; pauk owns success criteria,
  km totals, message counts, and highscores.

- Store quest definitions server-side (scenario, role prompt,
  success criteria, max_messages, optional graph/map refs).
  Reuse quiz_runs-style tracking for highscores (numeric
  score: km, messages used).

LLM provider (pluggable, in order of preference):

1. the `claude` CLI (already installed) — spawn non-interactive
   with a framing prompt and a machine-readable verdict. No new
   infra. Default.

2. a Claude API key (Anthropic SDK) — portable option for
   machines without the CLI. Requires the user's own key; a
   standard Claude/ChatGPT subscription does NOT include API
   access, so this is opt-in.

3. a tiny bundled local model (llama.cpp + a ~1-2 GB quantized
   model) — fits 4 GB/no-GPU but is unreliable as a judge;
   offer later as an explicit offline fallback, do not build on
   it.

Prereqs done: media (issues/0003), the autobahn graph, and the
route renderer. Next: spec the quest data model and the
provider interface in docs/api.md before implementing.

2026-09-09 (loop iteration 3, API 0.6.0 / CLI 0.9.0): quest
card type shipped. Dialog runs client-side via a pluggable
Provider (claude CLI implemented; local llama placeholder).
Scenario/role/criteria/max_messages stored in quest_specs;
POST /cards/{id}/quest-run records success + messages_used
(fewest-messages highscore) and logs to reviews. TUI
QuestScreen plays it in-character inside the quiz flow. Italian
quests (bakery/train/restaurant) live. Still open: wire the
local llama runtime (download + inference); route/annotation
map quests (next iteration).
