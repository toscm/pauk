# Architecture

## Components

- `spec` + `api`: the HTTP API is the single source of truth.
  Every client talks to it; nothing else touches the database.
  Implementation: PHP 8.4, Slim 4 framework, PDO. Chosen
  because it runs on the already-paid IONOS shared webhosting;
  the language is an implementation detail behind the spec.

- `cli`: Python 3 client. Started without arguments it runs a
  full-screen Textual app (home → deck picker with a favorites
  list and a directory tree → quiz screen with inline images →
  results with top-3 and repeat). Network calls run in
  background worker threads so the UI never blocks. The Typer
  subcommands (config/login/ls/add/rm/quiz/stats/media/import/
  update) remain the scripting interface and are covered by the
  e2e tests; a pexpect pty test guards real-terminal input.

- `web` (later): static single-page app served from the same
  webspace, talking to the same API.

- Mobile (later): starts as a PWA built from `web`.

## Hosting

- https://pauk.aao756.de → IONOS webspace, docroot
  `~/web/pauk`. TLS via the contract's wildcard certificate
  (`*.aao756.de`, auto-renewed by IONOS).

- Only `api/public/` is deployed into the docroot. Application
  code, vendor libraries, and configuration live outside it
  (`~/pauk-app`, `~/pauk-config`), so they are never served
  directly.

- Media files are stored on disk under the docroot
  (`media/<sha256>.<ext>`) and served statically by Apache.
  The database stores only metadata.

- Database: managed IONOS MariaDB 11.8 (2 GB), reachable only
  from the webspace or through an SSH tunnel.

## Data model

- `users`: id, name, created_at. Single user in practice for
  now, but every owned table carries `user_id` from day one
  because retrofitting it is painful.

- `api_tokens`: id, user_id, token_hash, label, created_at,
  last_used_at. Tokens are random 32-byte values, stored
  hashed (SHA-256).

- `cards`: id, user_id, type (`mc` | `text` | `match` |
  `quest` | `route` | `recall`), question_md, created_at,
  updated_at.
  Cards carry no path; where they appear is defined solely by
  directory links.

- `mc_options`: id, card_id, position, text_md, is_correct.
  Multiple correct options are allowed.

- `text_answers`: id, card_id, accepted_answer. Several rows
  mean several accepted phrasings.

- `match_pairs`: id, card_id, position, left_md, right_md.
  The shared row id is the correct connection; quiz mode
  shuffles the right side.

- `recall_cards`: card_id, answer_md.
  A self-graded free-recall card: the client reveals the reference answer and the learner's own verdict reaches the API via `POST /cards/{id}/self-grade`, which logs it to `reviews`.
  No server-side grading, no highscore.

- `quest_specs` / `quest_runs`: an LLM-dialog task (scenario,
  role prompt, success criteria, max_messages, lang) and its
  finished attempts (success, messages_used) — fewest
  messages wins.

- `route_specs` / `route_runs`: a graph-navigation task
  (graph_name, start_node, goal_node) and its attempts
  (success, km) — fewest km wins. The graph is bundled in
  the client; km are summed client-side, never by an LLM.

- `dirs`: id, user_id, name, created_at, updated_at. A
  directory is a collection, not a filesystem node.

- `dir_dirs`: parent_id, child_id — directory nesting edges.

- `dir_cards`: dir_id, card_id — card membership edges.

- `media`: id, user_id, sha256, original_name, mime, size,
  created_at. The file on disk is `<sha256>.<ext>`; uploading
  the same content twice deduplicates naturally.

- `reviews`: card_id, user_id, answered_at, was_correct.
  Append-only log of card answers; drives quiz selection.

- Knowledge profile (docs/tutor.md, migration 008):

  - `items`: one piece of knowledge per row, identity `(space, key)` (binary collation), kind, label/gloss/body, attrs JSON with generated unique columns for the strong identifiers `doi`/`isbn`/`wikidata`, `label_norm` and the generated `key_base` for duplicate candidates, priority, level, `archived_at`, `merged_into`.
  - `item_aliases`: old keys and alternate names (key form) per space, with origin and reason.
  - `item_links`: `form_of` / `requires` / `part_of` / `related` edges, with a note (e.g. why two similar items are distinct).
  - `dir_items` (subjects) and `card_items` (cards as exercises for items).
  - `interactions` + `interaction_items`: the append-only evidence log, raw exercise and response, grader version, `occurred_at` with millisecond precision, per-item outcome and `origin_item_id`; `interaction_amendments` for corrections.
  - `item_states`: cache of the memory model over the log (stability, difficulty, reps, lapses, best mode, model version) plus the two learner flags status and note.
  - `item_merges`: suggested and executed merges with what they moved, so unmerge is exact.
  - `user_settings`: one JSON value per setting name.

- `quiz_runs`: user_id, dir_id (nullable; a deleted dir
  keeps its runs with NULL), total, correct, started_at,
  finished_at. Started runs drive the picker's popularity
  sorting, finished runs the per-directory top-3 ranking.

### Directory semantics

Directories form a DAG, not a tree:

- A card can be linked into any number of directories; a
  directory can be linked into any number of parent
  directories. Example: `italian-core-verbs` is both a
  quiz of its own and a subdirectory of `italian-verbs`;
  quizzing the latter includes the former's cards
  transitively.

- Cycles are forbidden and rejected when a nesting edge is
  created (the API walks the would-be ancestors).

- A directory has one name (`^[a-z0-9-]+$`), the same under
  every parent. Siblings must have distinct names, and
  top-level directories (those without parents) must have
  distinct names per user, so a path like
  `italian-verbs/italian-core-verbs` resolves uniquely —
  though a directory may be reachable via several paths.

- Cards linked into no directory are "unfiled" and listable
  as such; deleting a directory never deletes cards.

- Sharing later: visibility will be a property of
  directories (e.g. everything under a user's `public`
  directory is readable by others), which multi-membership
  makes cheap — sharing is linking. Not part of milestone 1.

### Schema conventions

- Names: all-lowercase snake_case everywhere (sidesteps
  MariaDB's filesystem-dependent table-name case
  sensitivity). Tables plural (`cards`, `dirs`), columns
  singular, PK `id` (BIGINT UNSIGNED AUTO_INCREMENT), FKs
  `<singular>_id`, role-named on self-references
  (`parent_id`, `child_id`). Junction tables are named
  container-first (`dir_cards`, `dir_dirs`) and use a
  composite PK over their two columns, no surrogate id.

- InnoDB, utf8mb4. FK constraints with ON DELETE CASCADE on
  junction tables, so deleting an entity cleans up its edges.

- The directory DAG is stored as an edge table. Single-dir
  traversal uses a recursive CTE (`WITH RECURSIVE`), with
  `UNION` dedup making it diamond-safe and loop-safe. Caution:
  the CTE's column type is inferred from the anchor query, and
  a bare bound parameter is typed as a short string that
  silently truncates deeper ids — always write the anchor as
  `SELECT CAST(? AS UNSIGNED)`. The quiz-picker listing, which
  needs the transitive card count of *every* directory at once,
  instead loads all edges and memberships in a few queries and
  computes the closures in PHP — one recursive CTE per
  directory would be an N+1 against the remote production DB.
  No closure table — unnecessary at this scale.

## Decisions

- Design principle: as simple as possible, follow mainstream
  conventions wherever one exists, so that code and app feel
  familiar from the first minute.

- Name components by role, not language (`api`, not
  `pauk-php`): the contract outlives the implementation.

- Monorepo while the project is small; a native mobile app
  would get its own repo because of its toolchain.

- One database engine everywhere: MariaDB 11.8 in
  production, in CI, and locally (user-space install from
  the official binary tarball, scratch datadirs under
  `api/var/`). No SQLite, no dialect-portability rules —
  plain MariaDB SQL is fine. See docs/development.md.

- Directories are a DAG of collections (see above); cards
  have no intrinsic path. Tags from an earlier draft were
  dropped: a multi-membership directory does everything a
  tag did (issues/0008 tracks whether they are ever missed).

- Answer grading happens server-side (`POST
  /cards/{id}/answer`), so every client grades identically
  and accepted answers never need to be exposed for quizzing.

- Question selection is also server-side (`GET /quiz/cards`):
  weighted random sampling favoring new, error-prone, and
  stale cards, computed from the reviews log. Chosen over
  plain random (ignores history) and over full SRS
  scheduling like Leitner/SM-2/FSRS (due-date based,
  overkill for v1, and it would refuse to quiz cards that
  are "not due"); the endpoint is the seam where real SRS
  can slot in later (issues/0005).

- Auth is static bearer tokens for now. No sessions, no
  OAuth; the web interface can move to something richer later
  without breaking the token scheme.

- Client responsiveness is an accelerator layer, not a second
  source of truth: the CLI keeps its API connection warm
  (keep-alive, startup prewarm) and serves the read-heavy picker
  and quiz GETs from a small stale-while-revalidate file cache
  (`cli/pauk/cache.py`, under `~/.cache/pauk/`, keyed per
  server+token). The API stays authoritative — every write busts
  the cache, and `--no-cache` / `PAUK_NO_CACHE` turn it off.
  Chosen over migrating hosting or syncing a local SQLite copy
  (issues/0012 item 8): caching is the simplest change that makes
  the TUI feel instant without duplicating the data model.

- The quest/tip LLM runs locally by default: an in-process
  GGUF model via llama.cpp, packaged as the optional
  `pauk[local]` extra (no API key, no subscription, no
  always-on daemon). `pauk.llm.hardware` picks a model tier
  from RAM + accelerator (a small curated table, 0.5B–32B
  Q4_K_M) and the model is fetched lazily into
  `~/.cache/pauk/models/` on first use. `default_provider()`
  prefers the local runtime, falls back to the `claude` CLI,
  then errors. Chosen over an API key (cost, opt-in) and an
  always-running Ollama daemon (extra infra) for a single-user
  hobby app. The wrapped model id shows in the status bar.

- Recall cards are the one exception to server-side grading, by design.
  Their answers are several sentences of prose that no string matcher can judge, so the reference answer travels to the client and the learner decides.
  The API still owns the review log: the verdict is submitted through `POST /cards/{id}/self-grade`, never through `/answer`, so selection weighting and deck performance treat recall like any other card.

- A tip is scored as neither right nor wrong: requesting a
  hint for a card suppresses the `POST /cards/{id}/answer`
  call entirely, so no review is logged and the card is not
  rescheduled. Grading stays server-side for everything
  actually answered; the client simply declines to submit a
  tipped card.

- Knowledge over cards: pauk moves from static cards to a per-user knowledge profile and an LLM tutor (docs/tutor.md, issues/0014).
  The profile is added beside cards and directories, not instead of them: cards become exercises linked to items, directories become subjects that hold items too, and answering a linked card is evidence for its items.
  Chosen over a restructure because the card schema is orthogonal to the new one and every migration must stay additive.

- Computations are deterministic, judgements of meaning belong to the LLM.
  Scores, keyed grading and selection are code in the API; whether two names denote the same thing, whether an open answer is right, or what the learner intends are decided by the LLM.
  The API makes those decisions cheap to get right and cheap to undo: it resolves only exact identity (key, alias, DOI/ISBN/Wikidata), returns lexical candidates that the caller must answer with `same_as` or `distinct_from` plus a reason, and keeps merges reversible.

- Identity spaces are separate from subjects.
  An item lives in exactly one space (a language, or `concepts`), which only prevents false collisions; subjects are directories with many-to-many membership, so `concepts/linear-regression` exists once and belongs to statistics, bioinformatics and phd-defense.

- The interaction log is the truth and is never rewritten: corrections are amendment rows, items are archived rather than deleted, merges repoint rows while keeping `origin_item_id`.
  Item states are a cache of a versioned, pure memory model (`Pauk\Knowledge\MemoryModel`, v1 `pauk-mm@1`, FSRS-inspired stability/difficulty with a power forgetting curve); `POST /admin/rebuild-states` recomputes them, and a test asserts that a rebuild reproduces the incremental states.
  The model constants are not part of the API contract, so retuning or replacing the model is a code change plus a rebuild.
  v1 constants: mode factors recognize 0.6, recall 1.0, produce 1.2, explain 1.0, self_report 0.5; first stability 1/3/8 days (hard/good/easy, times the mode factor) or 0.2 on fail; growth `1 + m·k·((11−D)/10)·S^−0.15·(e^(2(1−R))−1)` with k = 4/10/16; after a fail `max(0.2, min(S/2, 0.5 + 0.1·S))`.

- Open value sets (item kind, link rel, interaction mode and source, best mode, grader, merge status) are VARCHAR validated by the API; ENUM only for closed sets (outcome, flag status). `cards.type` needed four ENUM migrations.

- All timestamps are UTC: every connection sets `time_zone = '+00:00'`.
  Before 0.10.0 the session used the server zone (Europe/Berlin locally, likely also on IONOS) while the API labelled times with `Z`; rows written before that are off by the zone offset, which is harmless for quiz staleness and leaderboards.

### TUI gotchas

- Never name a Textual widget/Screen instance attribute `path`.
  It shadows a Textual internal used during rendering and makes
  the screen crash with `'NoneType' has no attribute
  'render_strips'` on every terminal (not just headless).
  RouteScreen uses `node_path`. When adding a screen, prefer
  prefixed attribute names to avoid colliding with framework
  internals.
