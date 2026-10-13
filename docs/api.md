# API specification

Base URL: `https://pauk.aao756.de/api/v1`

This document is the contract between the API and all
clients. (A machine-readable `spec/openapi.yaml` was planned
but not yet generated; until it exists, this document and the
integration tests are the contract.)

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

- Compatibility: clients ignore unknown fields; string fields with enumerated values may gain new values; additive changes do not bump `/api/v1`.

- Some errors carry extra top-level fields next to `error`, e.g. the `candidates` of a `possible_duplicates` 409 (see Knowledge items).

## Health

`GET /health` (no auth)

    {"status": "ok", "db": "ok", "version": "0.10.0"}

`version` is the deployed API version (currently 0.10.0); the
example tracks it only loosely.

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

Matching cards have `"type": "match"` and, instead of
`options`, a `pairs` list — each pair a left and a right the
user must connect (e.g. a pronoun and the matching verb
form):

    {"id": 20, "type": "match",
     "question_md": "Match each pronoun to the form of **parlare**",
     "pairs": [
       {"id": 5, "left_md": "io",       "right_md": "parlo"},
       {"id": 6, "left_md": "tu",       "right_md": "parli"},
       {"id": 7, "left_md": "lui/lei",  "right_md": "parla"}
     ], "dirs": [...], ...}

In quiz form (`quiz=1`) a match card omits the pairing:
`lefts` lists the left items in order, `choices` lists the
right items shuffled; a left matches the choice with the
same `id`.

    {"id": 20, "type": "match",
     "question_md": "...",
     "lefts":   [{"id": 5, "left_md": "io"}, {"id": 6, "left_md": "tu"}],
     "choices": [{"id": 6, "right_md": "parli"}, {"id": 5, "right_md": "parlo"}]}

- `GET /cards` — list. Filters: `dir` (directory id;
  add `recursive=1` to include all transitive
  subdirectories, deduplicated), `unfiled=1` (cards in no
  directory), `type`, `q` (substring search in question_md).
  Add `quiz=1` to omit `correct` flags and
  `accepted_answers` (for quizzing UIs).

- `POST /cards` — create. Body: `type`, `question_md`, plus
  the type-specific fields shown in the card sections above:
  `options` (mc), `accepted_answers` (text), `pairs` (match),
  `answer_md` (recall — the reference answer), `scenario_md`/
  `role_prompt`/`success_criteria`/`max_messages`/`lang` (quest
  — the scenario becomes `question_md`), or `graph_name`/
  `start_node`/`goal_node` (route). Optional `dirs` (list of
  directory ids to link into). Returns 201 + the card.

- `GET /cards/{id}` — single card. `?quiz=1` as above.

- `PATCH /cards/{id}` — partial update; any subset of the
  POST fields. Sending `options`, `accepted_answers`, or
  `dirs` replaces the whole respective set. Returns the
  updated card.

- `DELETE /cards/{id}` — 204. Removes its directory links;
  does not delete referenced media.

Quest cards have `"type": "quest"` and, instead of the above,
a spec the client uses to run a dialog with an LLM:

    {"id": 30, "type": "quest",
     "scenario_md": "You are at an Italian bakery. Order 2
       croissants and 1 coffee. The baker speaks only Italian.",
     "role_prompt": "You are a friendly Italian baker who speaks
       only Italian. Stay in character.",
     "success_criteria": "The customer clearly ordered 2
       croissants and 1 coffee in Italian.",
     "max_messages": 10, "lang": "it", "dirs": [...], ...}

The dialog and the success judgement run entirely client-side
(the CLI drives the provider chosen by `pauk.llm.hardware`);
the API never calls an LLM. Quiz mode returns the same fields
(a user owns their own quest content).

Route cards have `"type": "route"` and navigate a named graph
from a start node to a goal node (the graph itself is bundled
in the client). Kilometres are summed client-side from the
graph, never trusted to a model.

    {"id": 31, "type": "route",
     "question_md": "Drive from München to Berlin ...",
     "graph_name": "germany-autobahn",
     "start_node": "muenchen", "goal_node": "berlin",
     "dirs": [...], ...}

Recall cards have `"type": "recall"` and are self-graded: the
learner reads a (possibly long) question, thinks or writes an
answer, then reveals a stored reference answer and decides for
themselves whether they were right. There is no automatic
string matching, so questions can require several sentences.

    {"id": 40, "type": "recall",
     "question_md": "Explain why the EM algorithm converges.",
     "answer_md": "Each E-step/M-step pair cannot decrease the
       likelihood because ...",
     "dirs": [...], ...}

`answer_md` is required on create and can be updated via PATCH.
Unlike mc/text/match, a recall card keeps `answer_md` in quiz
form (`quiz=1`): there is no server-side grading to protect, so
the client reveals the reference answer for the learner to
assess themselves.

quest, route, and recall cards are not answered via
`POST /cards/{id}/answer` (that returns 400 for them); quest
and route are recorded via `/quest-run` and `/route-run`, and
recall via `/self-grade`, below.

## Answering

`POST /cards/{id}/answer`

Multiple choice: `{"selected": [1, 3]}` (option ids).
Correct iff the selected set equals the set of correct
option ids.

Matching: `{"matches": {"5": 5, "6": 7}}` — a map from each
left item's id to the chosen right item's id. A pair is
correct when the chosen right id equals the left id; the
card is correct iff every pair is. Response adds `detail`, a
per-left list of `{left, chosen_right, correct_right, ok}`;
`expected` holds the full `pairs`. `match` is `"exact"` or
`"wrong"`.

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

## Quest runs

`POST /cards/{id}/quest-run` — record a finished quest attempt.
Body: `success` (boolean), `messages_used` (integer). The run
is appended to the `reviews` log (`was_correct = success`, so
quests feed the weighted selection and stats) and to
`quest_runs`. Response:

    {"success": true, "messages_used": 6,
     "best_messages": 6, "rank": 1,
     "top": [{"messages_used": 6, "finished_at": "..."}]}

`best_messages` is the fewest messages among the user's
successful runs of this quest (null if none); `top` is the
best three successful runs (fewest messages, ties by earlier
finish); `rank` is this run's place among them, or null.

`POST /cards/{id}/route-run` — record a finished route
attempt. Body: `success` (boolean), `km` (integer). Logged
to `reviews` and `route_runs`. Response mirrors quest-run
with `best_km` (fewest km among successful runs) and a `top`
of `{km, finished_at}`. The highscore is the fewest km.

## Self-grading (recall)

`POST /cards/{id}/self-grade` — record a self-assessed recall
attempt. Body: `correct` (boolean — the learner's own verdict
after revealing the reference answer). The verdict is appended
to the `reviews` log (`was_correct = correct`, so recall feeds
the weighted selection and the performance metric). Returns:

    {"correct": true}

Returns 404 if the card is not a recall card (mirroring
quest-run/route-run on the wrong type; recall has no highscore,
so there is no `top`/`rank`). Recall is client-graded and is
therefore never sent to `POST /cards/{id}/answer`.

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

## Quiz picker and runs

`GET /quiz/dirs` — flat list of all directories for quiz
pickers, sorted by popularity (started runs) then path:

    {"items": [{
      "id": 3,
      "path": "italian/verbs/core-verbs",
      "name": "core-verbs",
      "cards_total": 20,
      "runs": 5,
      "performance": 0.62
    }]}

`path` is the canonical path (alphabetically first when a
directory is reachable via several). `performance` is a
rolling metric over the last 500 reviews of the directory's
transitive card set: `(correct - wrong) / total`, in
`[-1, 1]` (equivalently `2·mean(was_correct) - 1`), or null
when the subtree has no reviews. Because it aggregates over
the subtree, training `greek/lowercase` also moves `greek`.
This endpoint is batched: a fixed number of queries
regardless of directory count.

`POST /quiz/runs` — log a quiz start. Body: `dir_id`
(integer or null for all-cards quizzes), `total` (planned
question count), `ranked` (boolean, default true — repeat
and repeat-wrong runs pass false so they never enter a
leaderboard). Returns 201:

    {"id": 7, "best": {"correct": 18, "total": 20, "accuracy": 0.9}}

`best` is the current best ranked run for this exact
`(dir, total)` — so the quiz can show "best for n=20: 90%"
up front — or null. Run counts drive the popularity sorting.

`PATCH /quiz/runs/{id}` — finish a run. Body: `correct`,
`total` (actually answered; may be less than planned when
the user quits early). Response:

    {"id": 7, "correct": 18, "total": 20, "ranked": true,
     "rank": 2,
     "top": [{"correct": 19, "total": 20, "accuracy": 0.95, "finished_at": ...},
             {"correct": 18, "total": 20, "accuracy": 0.9,  "finished_at": ...}]}

Leaderboards are per `(dir, total)`, so n=5 and n=20 have
separate top-3 lists and a repeated subset never competes
with a full run. `top` holds the top three ranked runs for
this run's `(dir, total)` (by accuracy, ties broken by
earlier finish); `rank` is this run's 1-based position, or
null when unranked or outside the top three. Runs with
`total` 0, and runs with `ranked` false, are never ranked.

## Statistics

`GET /stats` — same filters as `GET /cards` (`dir`,
`recursive`, `unfiled`, `type`, `q`):

    {"summary": {"cards": 20, "asked_cards": 12,
                 "reviews": 40, "correct": 30,
                 "accuracy": 0.75},
     "items": [{"id": 17, "question_md": "...",
                "asked": 4, "correct": 1,
                "accuracy": 0.25,
                "last_answered": "2026-09-09T10:00:00Z"}]}

`accuracy` is correct/asked. `items` contains only cards
that were asked at least once, sorted worst accuracy first
(ties: more recently asked first), capped at 200 rows.

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
see issues/0006. In production Apache serves them from the
docroot `media/` directory; under the dev server the front
controller emits them from `PAUK_MEDIA_DIR`. Content JSON may
reference a not-yet-uploaded file as `media:<relative path>`
(resolved against the content file's own directory) in a
card's `question_md` or an mc option's `text_md`; `pauk
import` uploads it and substitutes the returned URL.

## Knowledge profile

The knowledge profile is designed in docs/tutor.md (sections 4–6); this section is the contract.
Everything here is per user.

### Knowledge items

An item is one piece of knowledge with an identity `space/key`, its ref:

- `space` is the identity namespace: a language code (`it`, `el`, `de`, `en`) for language-bound knowledge, `concepts` for everything language-independent; `^[a-z][a-z0-9-]{0,15}$`.

- `key` is lowercase ASCII slugs separated by dots: `parlare`, `essere.pres.1sg`, `pesca.fishing`, `park-2006-flow-cytometry-gating`.
  Kind prefixes (`term.x`) and part-of-speech suffixes (`x.noun`) are rejected.
  For `word`, `phrase` and `term` items the key may be omitted and is derived from the label (`α` → `alpha`, `In bocca al lupo!` → `in-bocca-al-lupo`); an optional `sense` appends a suffix (`pesca` + sense `fishing` → `pesca.fishing`).

- `kind`: `word`, `form`, `phrase`, `rule`, `symbol`, `term`, `fact`, `paper`, `skill`, `other`.
  A `form` key is `<lexeme-key>.<cell>`; the lexeme must exist and gets a `form_of` link automatically.

Item object:

    {"id": 12, "ref": "it/farfalla", "space": "it", "key": "farfalla",
     "kind": "word", "label_md": "farfalla", "gloss_md": "butterfly",
     "body_md": "", "attrs": {"pos": "noun", "gender": "f"},
     "priority": 70, "level": 1, "archived": false, "merged_into": null,
     "state": {"mastery": 3, "recall": 0.84, "stability": 6.2, "difficulty": 4.8,
               "reps": 3, "lapses": 0, "best_mode": "recall",
               "first_seen_at": "...", "last_seen_at": "...",
               "status": "active", "note": "", "model": "pauk-mm@1"},
     "created_at": "...", "updated_at": "..."}

- `priority` 0–100 (default 50), `level` 1–6 or null (difficulty tier, CEFR A1–C2 for languages).

- `attrs` is free JSON; `doi`, `isbn` and `wikidata` are strong identifiers, unique per user (DOIs are lowercased).

- `state` is null for an item without evidence or flags.
  `mastery` is 0 unseen, 1 introduced, 2 fragile, 3 learning, 4 known, 5 mastered; `recall` is the current recall probability (null when unseen).
  How `stability`, `difficulty` and `recall` are computed is not part of the contract; `model` names the version that computed them.

- The single-item view (`GET /items/{ref}`) adds `aliases`, `dirs` (subjects), `links` (each `{direction: out|in, rel, ref, label_md, note}`), `cards` (linked card ids) and the last 10 `interactions`.

Items are addressed as `/items/{space}/{key}` or `/items/{id}`; an alias or the key of a merged item resolves to the current item.

- `GET /items` — list. Filters: `space`, `kind`, `q` (label, gloss, body, key, aliases), `status`, `dir` (+ `recursive=1`), `archived=1` to include archived items. Paginated.

- `POST /items` — create. Body: the item fields, optional `dirs` (directory ids), `links` (`[{rel, to}]`, `to` a ref or a key in the same space), and the duplicate protocol below. 201 `{"created": true, "item": ...}`.

- `PUT /items/bulk` — `{"items": [...]}`, at most 500, upsert by exact identity, no candidate checks. Links may point forward within the batch. Response: `created`, `updated`, `unchanged`, `refs`, `conflicts` (an item with `attrs.origin = "teacher"` whose gloss differs is not overwritten), `possible_duplicates` (same normalized label as a teacher-added item), `unresolved_links`.

- `GET /items/{ref}`, `PATCH /items/{ref}` (any item field; a new `key` leaves the old one as an alias; 409 on a key clash).

- `POST /items/{ref}/archive`, `POST /items/{ref}/unarchive`. Items are never deleted.

- `PUT /items/{ref}/state` — the learner flags `status` (`active`, `focus`, `suspended`) and `note`.

- `PUT /items/{ref}/links` `{rel, to, note?}`, `DELETE /items/{ref}/links?rel=&to=` — `rel` is `form_of`, `requires`, `part_of` or `related`.

- `PUT|DELETE /dirs/{id}/items/{ref}` — subject membership (directories hold items as well as cards).

- `PUT|DELETE /cards/{id}/items/{ref}` — link a card to the items it tests. The first link backfills the past reviews of the card as interactions (`source: card`, original time); afterwards every answer and self-grade of the card is recorded for its items (mc/match → `recognize`, text/recall → `recall`; exact → `good`, typo → `hard`, wrong → `fail`).

### Duplicate protocol

`POST /items` decides only exact identity itself; whether two different names mean the same thing is decided by the caller (normally an LLM).

1. Exact identity — same key, an alias, or the same strong identifier: 200 `{"created": false, "via": "key" | "alias" | "doi" | "isbn" | "wikidata", "item": ...}`.

2. Otherwise the API looks for candidates (same normalized label or key base, whole-word containment, similar spelling for non-lexical kinds, the label in the gloss of another item, the same label in another space for non-lexical kinds).
   If there are any, nothing is created:

       409 {"error": {"code": "possible_duplicates", "message": "..."},
            "candidates": [{"ref": "it/pesca", "kind": "word", "label_md": "pesca",
                            "gloss_md": "peach", "reason": "label"}]}

3. The caller resends with a decision:

   - `"same_as": REF` (+ optional `reason`): nothing is created; the label (and key) become aliases of REF. 200 `{"created": false, "via": "same_as", "item": ...}`.
   - `"distinct_from": [REF, ...]` + `"reason"`: must cover every candidate; the item is created and each pair stored as a `related` link with the reason.

### Interactions

An interaction is one observed learner event with an outcome per item; the log is append-only.

`POST /interactions`:

    {"uuid": "6f1c...", "occurred_at": "2026-10-13T10:00:00.250Z",
     "mode": "recall", "source": "tutor", "session_id": "s-42",
     "exercise": {"kind": "text", "prompt_md": "...", "accepted": ["farfalla"]},
     "response": {"text": "farfala"},
     "hinted": false, "prompt_md": "...", "response_md": "...", "feedback_md": "...",
     "items": [{"ref": "it/farfalla"}, {"ref": "it/present-are", "outcome": "fail", "note": "..."}]}

- `uuid` (RFC 4122, lowercase) makes recording idempotent: a retry returns the original result with 200 and `"created": false`. Generated when omitted.

- `mode`: `introduce` (no outcomes), `recognize`, `recall`, `produce`, `explain`, `self_report`. `source`: `tutor`, `card`, `import`, `activity`, `simulation` (default `tutor`). `occurred_at` defaults to now.

- `outcome` per item: `fail`, `hard`, `good`, `easy`. A hinted interaction counts at most as `hard`. When the caller judged the outcomes, an optional `grader` label says who (`teacher`, `self`, ...); API-graded interactions carry the versioned grader name (`text@1`).

- Keyed exercises are graded by the API when outcomes are omitted: `mc` (`options` `[{id, text_md}]`, `correct` ids; response `{"selected": [ids]}`), `match` (`pairs` in correct order; response `{"matches": {"0": 0, "1": 1}}` left index → pair index), `text` (`accepted`; response `{"text": ...}`, graded like card answers). The outcome applies to every item without an explicit one; the response adds `match`, `correct` and `expected`.

Response 201:

    {"uuid": "6f1c...", "created": true, "match": "typo", "correct": true,
     "expected": {"accepted": ["farfalla"]},
     "items": [{"ref": "it/farfalla", "outcome": "hard", "mastery_before": 1, "state": {...}}]}

- `POST /interactions/{uuid}/amendments` `{items: [{ref, outcome}], reason, by}` — corrects outcomes without editing the log (`by`: `teacher`, `observer`, `human`); the latest amendment wins and the states of the items are recomputed.

- `GET /interactions?item=&session_id=&since=` — history (paginated), each with its raw `exercise`, `response`, `grader`, per-item outcomes with their `origin` item, and `amendments`.

### Merges

- `POST /items/{ref}/merge` `{from, reason, by?, session_id?}` — merge `from` into `ref`: evidence, card and subject links, item links and aliases move over, the state is recomputed from the combined log, `from` is archived and its key resolves to `ref`. `by`: `teacher`, `observer`, `sweep`, `human` (default). Returns the merge object.

- `POST /items/{ref}/unmerge` — undo the latest merge of `ref` into another item exactly.

- `POST /merges` `{into, from, reason, by}` — suggest a merge (201); `GET /merges?status=suggested|done|dismissed|undone`; `POST /merges/{id}/accept`, `POST /merges/{id}/dismiss` (a dismissed pair is recorded as `related`).

Merge object: `{id, into, into_label_md, from, from_label_md, status, reason, suggested_by, session_id, created_at, decided_at}`.

### Profile and selection

- `GET /profile?dir=&space=&kind=` — `{"items": 120, "by_mastery": {"0": 80, ..., "5": 2}, "coverage": 0.41, "due": 7, "most_lapses": [{ref, label_md, lapses}]}`. `coverage` is Σ priority·recall / Σ priority. `dir` is recursive by default.

- `GET /profile/next?dir=&space=&n=10&new=` — what to practise next:

      {"review": [{"ref", "kind", "label_md", "gloss_md", "priority", "level", "state", "reason": "due: R=0.62"}],
       "new":    [{..., "reason": "new: priority 95, level 1"}]}

  `review`: items with evidence whose recall dropped below 0.9 (0.95 after two lapses), most urgent first, weighted by priority, `focus` counting double.
  `new`: unseen items whose `requires` prerequisites are all at mastery ≥ 3, by priority, then level, then key; at most `new` entries (default `n`), so a session can cap new items.
  Suspended and archived items are never offered.

### Settings

- `GET /settings` — all settings with defaults filled in.

- `PATCH /settings` — `{"tutor.language": "en", ...}`; unknown names or invalid values → 400.

Settings: `tutor.language` (BCP 47, default `de`), `tutor.immersion` (per space `off`/`partial`/`full`, default `{}`), `tutor.item_creation` (`off`, `propose`, `on_request`, `free`; default `propose`), `tutor.merge` (`propose`, `free`; default `propose`), `tutor.new_items_per_15min` (0–50, default 8), `review.after_session` (default true), `review.auto_triage` (default false).

### Export and maintenance

- `GET /export` — `application/x-ndjson`: a header `{"format": "pauk-export", "version": 1, ...}`, then `dir`, `item` (with aliases, outgoing links, subject ids, card ids, flags), `interaction` (raw evidence, outcomes, amendments) and `settings` records. States are not exported; they are recomputed on import.

- `POST /admin/rebuild-states` — recompute every state of the user from the log; `{"items": N}`.
