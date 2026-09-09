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

- Card paths must match `^(/[a-z0-9-]+)+$` (lowercase,
  digits, hyphens; no trailing slash). Tags must match
  `^[a-z0-9-]+$`.

## Health

`GET /health` (no auth)

    {"status": "ok", "db": "ok", "version": "0.1.0"}

`db` is `"ok"` or `"error"`; on error the HTTP status is 503.
Used by the post-deploy smoke test.

## Cards

Card object (as returned to its owner):

    {
      "id": 17,
      "path": "/bio/zellbiologie",
      "type": "mc",
      "question_md": "What does ![m](https://.../m.png) show?",
      "options": [
        {"id": 1, "text_md": "Mitochondrium", "correct": true},
        {"id": 2, "text_md": "Ribosom", "correct": false}
      ],
      "tags": ["exam", "bio"],
      "created_at": "2026-09-09T10:00:00Z",
      "updated_at": "2026-09-09T10:00:00Z"
    }

Free-text cards have `"type": "text"` and, instead of
`options`, `"accepted_answers": ["Mitochondrium"]`.

- `GET /cards` — list. Filters: `path` (exact),
  `path_prefix`, `tag` (repeatable, AND), `type`, `q`
  (substring search in question_md). Add `quiz=1` to omit
  `correct` flags and `accepted_answers` (for quizzing UIs).

- `POST /cards` — create. Body: `path`, `type`,
  `question_md`, plus `options` (mc; each `text_md` +
  `correct`, at least one correct) or `accepted_answers`
  (text; at least one non-empty). Optional `tags` (created
  on the fly). Returns 201 + the card.

- `GET /cards/{id}` — single card. `?quiz=1` as above.

- `PATCH /cards/{id}` — partial update; any subset of the
  POST fields. Sending `options` or `accepted_answers`
  replaces the whole set. Returns the updated card.

- `DELETE /cards/{id}` — 204. Does not delete referenced
  media.

## Answering

`POST /cards/{id}/answer`

Multiple choice: `{"selected": [1, 3]}` (option ids).
Correct iff the selected set equals the set of correct
option ids.

Free text: `{"answer": "mitochondrium"}`. Grading:

1. Normalize both sides: Unicode NFKD, casefold, strip
   diacritics and punctuation, collapse whitespace.
2. Exact match against any accepted answer → `"exact"`.
3. Levenshtein distance ≤ max(1, ⌊len/8⌋) (len = normalized
   accepted answer) → `"typo"`.
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

## Paths

`GET /paths` — all distinct paths with card counts,
sorted:

    {"items": [
      {"path": "/bio", "cards": 0, "total": 12},
      {"path": "/bio/zellbiologie", "cards": 12, "total": 12}
    ]}

`cards` counts cards exactly at the path, `total` includes
all descendants. Intermediate prefixes appear even if no
card sits on them directly.

## Tags

- `GET /tags` — `{"items": [{"name": "exam", "cards": 5}]}`
- `DELETE /tags/{name}` — removes the tag from all cards, 204.

Tags are created implicitly via card create/update.

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
