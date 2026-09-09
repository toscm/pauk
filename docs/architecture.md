# Architecture

## Components

- `spec` + `api`: the HTTP API is the single source of truth.
  Every client talks to it; nothing else touches the database.
  Implementation: PHP 8.4, Slim 4 framework, PDO. Chosen
  because it runs on the already-paid IONOS shared webhosting;
  the language is an implementation detail behind the spec.

- `cli`: Python 3 client (Typer + httpx + rich). Talks HTTP
  only, so it is independent of the API's implementation
  language.

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

- `cards`: id, user_id, path, type (`mc` | `text`),
  question_md, created_at, updated_at. `path` is a
  folder-like string such as `/bio/zellbiologie`; folders
  exist only as path prefixes, there is no folder table.

- `mc_options`: id, card_id, position, text_md, is_correct.
  Multiple correct options are allowed.

- `text_answers`: id, card_id, accepted_answer. Several rows
  mean several accepted phrasings.

- `tags`: id, user_id, name. `card_tags`: card_id, tag_id.

- `media`: id, user_id, sha256, original_name, mime, size,
  created_at. The file on disk is `<sha256>.<ext>`; uploading
  the same content twice deduplicates naturally.

- `reviews` (later): card_id, user_id, answered_at,
  was_correct. Append-only log a spaced-repetition scheduler
  can be built on.

## Decisions

- Name components by role, not language (`api`, not
  `pauk-php`): the contract outlives the implementation.

- Monorepo while the project is small; a native mobile app
  would get its own repo because of its toolchain.

- Two SQL dialects, one schema: production runs MariaDB,
  development and tests run SQLite. Consequences:

  - All queries stick to the portable SQL subset. No
    dialect-specific features (no `INSERT ... ON DUPLICATE
    KEY`, no FULLTEXT; search uses `LIKE` for now).

  - Migrations are plain SQL files in `api/migrations/`,
    numbered `NNN_name.sql`. Where the dialects must differ
    (e.g. auto-increment syntax), a migration exists as
    `NNN_name.mariadb.sql` plus `NNN_name.sqlite.sql` instead
    of the shared file. The migration runner picks the right
    variant.

  - CI additionally runs the test suite against a real
    MariaDB 11.8 service container to catch dialect drift
    (see docs/testing.md).

- Answer grading happens server-side (`POST
  /cards/{id}/answer`), so every client grades identically
  and accepted answers never need to be exposed for quizzing.

- Auth is static bearer tokens for now. No sessions, no
  OAuth; the web interface can move to something richer later
  without breaking the token scheme.
