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

- `cards`: id, user_id, type (`mc` | `text`), question_md,
  created_at, updated_at. Cards carry no path; where they
  appear is defined solely by directory links.

- `mc_options`: id, card_id, position, text_md, is_correct.
  Multiple correct options are allowed.

- `text_answers`: id, card_id, accepted_answer. Several rows
  mean several accepted phrasings.

- `dirs`: id, user_id, name, created_at, updated_at. A
  directory is a collection, not a filesystem node.

- `dir_dirs`: parent_id, child_id — directory nesting edges.

- `dir_cards`: dir_id, card_id — card membership edges.

- `media`: id, user_id, sha256, original_name, mime, size,
  created_at. The file on disk is `<sha256>.<ext>`; uploading
  the same content twice deduplicates naturally.

- `reviews` (later): card_id, user_id, answered_at,
  was_correct. Append-only log a spaced-repetition scheduler
  can be built on.

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

### TUI gotchas

- Never name a Textual widget/Screen instance attribute `path`.
  It shadows a Textual internal used during rendering and makes
  the screen crash with `'NoneType' has no attribute
  'render_strips'` on every terminal (not just headless).
  RouteScreen uses `node_path`. When adding a screen, prefer
  prefixed attribute names to avoid colliding with framework
  internals.
