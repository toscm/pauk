# API specification

Base URL: `https://pauk.aao756.de/api/v1`

This document is the contract between the API and all
clients. A machine-readable `spec/openapi.yaml` is derived
from it during milestone 1; if the two ever disagree, this
document wins until the discrepancy is fixed.

## Conventions

- All requests and responses are JSON (UTF-8), except media
  upload (multipart) and the media files themselves.

- Authentication: `Authorization: Bearer <token>` on every
  endpoint except `GET /health`. Missing/invalid token → 401.

- Errors always have the shape:

      {"error": {"code": "not_found", "message": "..."}}

  with a matching HTTP status (400 validation, 401 auth,
  404 missing, 409 conflict, 413 too large, 500 internal).

- Timestamps are ISO 8601 UTC strings, e.g.
  `2026-09-09T10:00:00Z`.

- List endpoints paginate with `?limit=` (default 50, max
  200) and `?cursor=`; responses contain `items` and
  `next_cursor` (null when exhausted).

- Directory names must match `^[a-z0-9-]+$`. Directory
  semantics (DAG, uniqueness, cycle rules) are defined in
  docs/architecture.md.

## Health

`GET /health` (no auth)

    {"status": "ok", "db": "ok", "version": "0.1.0"}

`db` is `"ok"` or `"error"`; on error the HTTP status is 503.
Used by the post-deploy smoke test.

## Cards

Card object (as returned to its owner):

    {
      "id": 17,
      "type": "mc",
      "question_md": "What does ![m](https://.../m.png) show?",
      "options": [
        {"id": 1, "text_md": "Mitochondrium", "correct": true},
        {"id": 2, "text_md": "Ribosom", "correct": false}
      ],
      "dirs": [{"id": 3, "name": "zellbiologie"}],
      "created_at": "2026-09-09T10:00:00Z",
      "updated_at": "2026-09-09T10:00:00Z"
    }

Free-text cards have `"type": "text"` and, instead of
`options`, `"accepted_answers": ["Mitochondrium"]`.

- `GET /cards` — list. Filters: `dir` (directory id;
  add `recursive=1` to include all transitive
  subdirectories, deduplicated), `unfiled=1` (cards in no
  directory), `type`, `q` (substring search in question_md).
  Add `quiz=1` to omit `correct` flags and
  `accepted_answers` (for quizzing UIs).

- `POST /cards` — create. Body: `type`, `question_md`, plus
  `options` (mc; each `text_md` + `correct`, at least one
  correct) or `accepted_answers` (text; at least one
  non-empty). Optional `dirs` (list of directory ids to link
  into). Returns 201 + the card.

- `GET /cards/{id}` — single card. `?quiz=1` as above.

- `PATCH /cards/{id}` — partial update; any subset of the
  POST fields. Sending `options`, `accepted_answers`, or
  `dirs` replaces the whole respective set. Returns the
  updated card.

- `DELETE /cards/{id}` — 204. Removes its directory links;
  does not delete referenced media.

## Answering

`POST /cards/{id}/answer`

Multiple choice: `{"selected": [1, 3]}` (option ids).
Correct iff the selected set equals the set of correct
option ids.

Free text: `{"answer": "mitochondrium"}`. Grading:

1. Normalize both sides: Unicode NFKD, casefold, strip
   diacritics and punctuation, collapse whitespace.
2. Exact match against any accepted answer → `"exact"`.
3. Levenshtein distance ≤ max(1, ⌊len/8⌋) (len = length of
   the normalized accepted answer) → `"typo"`. Accepted
   answers shorter than 4 characters allow no typo budget
   (a 1-edit budget would accept any letter for any other).
4. Otherwise → `"wrong"`.

Response (identical shape for both types):

    {
      "correct": true,
      "match": "typo",
      "expected": {
        "accepted_answers": ["Mitochondrium"]
      }
    }

For mc cards `expected` contains
`"correct_option_ids": [1, 3]` instead. `match` is
`"exact"`, `"typo"`, or `"wrong"` (mc: `"exact"`/`"wrong"`).
The answer is also appended to the `reviews` log.

## Quiz selection

`GET /quiz/cards?dir={id}&recursive=1&n=20`

Returns up to `n` (default 20) cards in quiz form (like
`quiz=1`: no `correct` flags, no `accepted_answers`),
selected from the candidate set (same filters as
`GET /cards`: `dir`, `recursive`, `unfiled`, `type`) by
weighted random sampling without replacement. Weights favor
cards that are new, rarely asked, often answered wrong, or
long unasked. Per card, from the user's `reviews`:

    error_rate = (wrong + 1) / (asked + 2)
    staleness  = 1 if never asked
                 else min(days_since_last_answer, 30) / 30
    weight     = error_rate * (1 + staleness)

The Laplace smoothing gives never-asked cards error_rate
0.5, so a new card gets the maximum weight 1.0, while a
frequently-correct, recently-seen card approaches the
floor. An optional `seed` (integer) makes the sampling
deterministic; it exists for tests.

Response: `{"items": [ ...card objects... ]}` (no
pagination; `n` is capped at 200).

Selection is server-side because the reviews log lives
here and all clients must quiz identically; real
spaced-repetition scheduling can later replace the formula
behind this same endpoint (issues/0005).

## Directories

Directory object:

    {
      "id": 3,
      "name": "italian-core-verbs",
      "parents": [{"id": 2, "name": "italian-verbs"}],
      "subdirs": [],
      "cards": 20,
      "cards_total": 20
    }

`cards` counts directly linked cards, `cards_total` counts
the transitive closure (deduplicated).

- `GET /dirs` — top-level directories (those without
  parents). `?parent={id}` lists the children of a
  directory instead.

- `GET /dirs/{id}` — single directory as above.

- `GET /dirs/resolve?path=italian-verbs/italian-core-verbs`
  — resolve a slash-separated name path from the top level;
  returns the directory object or 404. (Unique by the
  sibling-uniqueness rule, though other paths may reach the
  same directory.)

- `POST /dirs` — create. Body: `name`, optional `parent_id`.
  409 on a name clash among the new siblings.

- `PATCH /dirs/{id}` — rename. 409 on a clash under any of
  its parents.

- `DELETE /dirs/{id}` — delete the directory and all its
  edges; cards are never deleted. If a child directory would
  become unreachable (no other parent), the request fails
  with 409 unless `?force=1`, which recursively deletes such
  child directories (again keeping all cards). 204 on
  success.

Membership edges (all idempotent, 204; `PUT` returns 409 on
a cycle or sibling name clash):

- `PUT    /dirs/{id}/cards/{card_id}` — link a card
- `DELETE /dirs/{id}/cards/{card_id}` — unlink a card
- `PUT    /dirs/{id}/dirs/{child_id}` — link a subdirectory
- `DELETE /dirs/{id}/dirs/{child_id}` — unlink it

## Media

- `POST /media` — multipart upload, field `file`. Allowed:
  png, jpeg, gif, webp, svg, mp4, webm, pdf. Max 50 MB.
  Returns 201:

      {
        "id": 3,
        "url": "https://pauk.aao756.de/media/ab12...ef.png",
        "sha256": "ab12...ef",
        "original_name": "mito.png",
        "mime": "image/png",
        "size": 12345
      }

  Re-uploading identical content returns 200 and the
  existing object.

- `GET /media` — paginated list.

- `DELETE /media/{id}` — deletes metadata and file, 204.
  Refuses with 409 if any card's question_md references the
  URL.

Media URLs are meant to be pasted into `question_md` as
`![name](url)`. The files themselves are served statically
(no auth) — obscurity via hash filename is accepted for now;
see issues/0006.
