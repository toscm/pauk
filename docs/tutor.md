# Tutor: knowledge profile and learner–teacher chat

Status: draft design, not yet implemented (issues/0014).
Once accepted, the API parts move into `docs/api.md` (the contract) and the lasting decisions into `docs/architecture.md`.
Revision 4 (2026-10-13): two independent reviews folded in (item identity, evolvability), then two corrections by the owner: equivalence of items is judged by the LLM, not by server rules (4.10), and identity spaces are separated from subjects (4.1).

## 1. Goal

pauk is the glue between a personal knowledge base and the LLM the learner already runs locally.
Three ingredients:

- A knowledge profile per learner: every piece of knowledge they know or want to know (an Italian word, an irregular verb form, a grammar rule, a Greek letter, a biology term, a paper) with a memory state derived from evidence.

- An append-only log of interactions: every observation of the learner using a piece of knowledge, right or wrong, with a timestamp.
  The memory state is computed from this log, never typed in by hand.

- A chat session in the browser between the learner and a teacher.
  The teacher is an LLM agent (e.g. a `claude` CLI started by `pauk`) that reads the profile, picks what to practise, asks questions in many formats, and reports observations back.

The browser is the primary client: it can show images, maps, rendered math and interactive activities (section 14), which a terminal cannot.
The whole UI assumes a capable local LLM in the teacher role; there is no hosted, LLM-free web version.
The Textual TUI keeps working but is frozen and moved to the backlog (issues/0015).

Non-goals for now: multi-user classrooms, a hosted tutor, voice, generated images, real-time (twitch) games, a shared global item catalog.

## 2. Feasibility in one paragraph

Feasible, with one structural consequence: the chat cannot live on the IONOS shared hosting (PHP request/response only, no websockets, no long-running processes).
So the chat runs in a local "session host" started by `pauk` on 127.0.0.1, which serves the web UI, relays messages between browser and agent, and talks to the remote API for everything persistent.
The remote API stays the single source of truth for knowledge, interactions and scores.
The division of labour follows one rule: computations are deterministic, judgements of meaning belong to the LLM.
The LLM never computes scores, kilometres or keyed grades; it reports per-item outcomes, and the API updates the memory state, the same principle the quests already follow ("the LLM does roleplay and parsing; pauk owns the scoring").
But whether two terms mean the same thing, whether an open answer is right, or what the learner intends are questions no server rule can answer, so the LLM decides them.
pauk's job there is to hand the LLM the right material (candidates, references), to make every such decision visible and attributable, and to make it reversible, so a wrong call costs one correction, not lost data.
The main practical risks are LLM latency (5–15 s per teacher turn) and LLM sloppiness; the design answers them with keyed exercises graded instantly by the API, drills, a duplicate protocol that makes the LLM look at candidates, and a narrow, validated action set.

## 3. Terminology

- Item: one piece of knowledge, the smallest unit the teacher would test and judge on its own.
  Examples: `it/parlare`, `it/essere.pres.1sg` (irregular form), `it/present-are` (a rule of Italian), `el/alpha`, `concepts/t-cell`, `concepts/linear-regression`, `concepts/park-2006-flow-cytometry-gating` (a paper).

- Space: the identity namespace of an item (4.1): one per language for language-bound knowledge (`it`, `el`, `de`, `en`), and `concepts` for everything language-independent.
  Spaces only prevent false collisions (Italian *come* vs English *come*); they say nothing about subject.

- Item reference: `space/key`, the stable external identity of an item, used in commands, imports, exports and transcripts.
  Numeric ids exist only inside one database.

- Subject: a topic such as statistics, bioinformatics, flow cytometry, Italian A1 or "PhD defense".
  Subjects are the existing directories (a DAG of collections), and an item can be in any number of them.

- State: the learner's memory of one item (stability, difficulty, last seen, best mode, ...).

- Interaction: one observable learner event (an answered exercise, an introduction, a self-report), linked to one or more items with an outcome per item.

- Exercise: what the teacher shows and the learner answers (multiple choice, free text, matching, open question, recall).

- Session: one tutoring conversation, hosted locally.

- Roles: learner (usually the human), teacher (usually an LLM agent), observer (read-only, human or LLM, section 15).

- Activity: an interactive, stateful exercise such as a map or a small 2D scene, controllable by every role through the same API (section 14).

- Settings: per-user preferences stored in the remote database (4.11), so they survive sessions and machines.

## 4. Knowledge model

### 4.1 Spaces, subjects and item identity

Two different questions were mixed up in earlier drafts under the name "domain": what an item is (identity) and what it belongs to (subject).
They are now separate.

Identity: every item lives in exactly one space.

- Language spaces (`it`, `el`, `de`, `en`, ISO 639-1 codes) hold knowledge that only exists within a language: words, forms, phrases, grammar rules, letters of an alphabet.
  They are needed because words of different languages collide (`it/come` = how, `en/come`).

- `concepts` holds everything language-independent: terms, methods, theorems, facts, papers.
  `concepts/linear-regression` exists once, whether it comes up in statistics, bioinformatics or a paper; the learner's memory of it is one state.
  Its label is in one language, other names in other languages are aliases.

- New spaces are created only by imports or by the human; there will be a handful, not dozens.

Subjects: the existing directories, extended to hold items as well as cards (`dir_items`, the counterpart of `dir_cards`).
Directories are already a DAG with multi-membership, which is exactly what subjects need:

- `concepts/linear-regression` is linked into `statistics`, `bioinformatics` and `phd-defense` at once.
- `phd-defense` is a subject that groups items from several fields; it is a collection, not a home.
- `italian/a1` keeps containing cards and now also items from the `it` space.
- The teacher scopes everything by subject: `next --dir statistics` draws from the transitive item set of that directory, as `GET /quiz/cards` already does for cards.

Where an item came from (a deck, a lexicon, a teacher session) is recorded in `attrs.source` / `attrs.origin`, not in its identity.

Keys follow a fixed grammar, ASCII only, so they are typeable and stable:

    key    = base ("." segment)*
    base   = slug of the lemma, term or short title, without article
    slug   = [a-z0-9]+ ("-" [a-z0-9]+)*

- No kind prefixes (`term.`, `paper.`) and no part-of-speech suffixes (`.noun`): `kind` and `attrs.pos` hold that.

- Non-Latin labels get a transliterated key: label `α`, key `alpha`.

- Homographs: the bare base is the primary sense, further senses append an English gloss slug: `it/pesca` (peach), `it/pesca.fishing`.

- Forms: `<lexeme-key>.<cell>` (`it/essere.pres.1sg`); the lexeme must exist, and the API adds the `form_of` link itself.

- Papers: `<first-author>-<year>-<short-topic>` (`park-2006-flow-cytometry-gating`), with `attrs.doi`.

- The key is a stable handle, not a definition of sameness: two different keys can denote the same thing, which is what aliases and merges handle (4.10).
  For words, phrases and terms the key may be omitted on create, and the API derives it from the label.

- Strong external identifiers, where they exist, are identity the server can check exactly: `attrs.doi`, `attrs.isbn`, `attrs.wikidata` are unique per user, so two items with the same DOI are rejected (or resolved to the existing one) without asking anybody.

- `key` is stored with a binary collation (`utf8mb4_bin`) so `e`/`è` or case never collide implicitly; the grammar already excludes both.

### 4.2 Item granularity

"All Italian words incl. all forms" would explode combinatorially (a verb has 50+ forms), and most forms are predictable from a rule.
Rule of thumb: create an item for a thing whose knowledge you cannot infer from other items.

- One item per lexeme (`parlare`), with its meaning in `gloss_md` and grammatical data in `attrs`.

- One item per rule (`present-are`: -o, -i, -a, -iamo, -ate, -ano).

- One item per irregular form or irregular paradigm cell (`essere.pres.1sg` = sono), linked `form_of` the lexeme.

- Regular forms are not items: answering "parliamo" correctly is evidence for `parlare` and for `present-are`.

The teacher can still ask about any form; it just records the outcome against the lexeme and the rule.

### 4.3 Item fields

- `space`, `key`: see 4.1; unique per user.

- Subjects: via `dir_items` (4.1), any number per item.

- `kind`: `word`, `form`, `phrase`, `rule`, `symbol`, `term`, `fact`, `paper`, `skill`, `other`.

- `label_md`: what the item is, shown as its title (`parlare`, `α`, `FastRet (Schmidt et al. 2024)`).

- `label_norm`: `norm(label_md)` (4.10), written by the API, indexed; never sent by clients.

- `gloss_md`: the short answer / meaning (`to speak`, `alpha`).

- `body_md`: reference material the teacher grounds its questions and judgements in: examples, irregularities, mnemonic, abstract, key claims of a paper, images (`![..](url)` via the existing media endpoints).

- `attrs`: JSON for kind-specific data (`pos`, `gender`, `conjugation`, `freq_rank`, `cefr`, `doi`, `isbn`, `wikidata`, `image`, `source`, `origin`).

- `priority`: 0–100, general importance (default 50); per-subject overrides can be added on `dir_items` later if one global value proves too coarse.
  For vocabulary derived from a frequency rank: `priority = clamp(round(100 − 20·log10(rank)), 0, 100)` (rank 1 → 100, rank 100 → 60, rank 10 000 → 20).

- `level`: 1–6, difficulty tier (CEFR A1–C2 for languages, free otherwise), nullable.

- `archived_at`, `merged_into`: items are never hard-deleted (the log references them); archiving hides them everywhere and implies `suspended`.

### 4.4 Item links

Directed edges `from → to` with a relation:

- `form_of`: `essere.pres.1sg` → `essere`.

- `requires`: prerequisite; `passato-prossimo` → `avere`. New items are only offered once their prerequisites are known (level ≥ 3, see 4.7).

- `part_of`: `alpha` → `greek-alphabet` (a grouping item), `t-cell` → `adaptive-immunity`.

- `related`: confusable or associated items (`parlo` ↔ `parla`), useful for distractors in multiple choice.
  Also written automatically when someone confirms that two similar items are distinct (4.10).

### 4.5 Interactions

An interaction records what the learner did, and for each touched item an outcome:

- `mode`: how strong the evidence is.

  - `introduce`: the item was presented, nothing tested.
  - `recognize`: picked from options or matched (mc, match).
  - `recall`: produced from memory (free text, translation, self-graded recall).
  - `produce`: used correctly in a new context (sentence, cloze, conversation).
  - `explain`: explained in own words (concepts, papers), judged by the teacher.
  - `self_report`: the learner states they know it ("I know the Greek alphabet").

- `outcome` per item: `fail`, `hard`, `good`, `easy` (absent for `introduce`).
  `hard` = correct but with a typo, a hint, or visible struggle.
  A hinted answer is capped at `hard`.

- `source`: `tutor`, `card` (an answered pauk card linked to items), `import`, `activity`.

- What is needed to re-grade later, not just to display:

  - `exercise`: the full exercise object including its key (options, `correct`, `accepted`, pairs).
  - `response`: the raw structured response (`selected`, `matches`, `text`).
  - `grader`: which grader produced the outcome, versioned (`text@1`, `mc@1`, `teacher`, `self`).
  - `prompt_md`, `response_md`, `feedback_md` for display, and an optional per-item `note`.

- `occurred_at`: when it happened (client-supplied, millisecond precision; default now).
  `created_at` is only the insert time; imports, backfills and retried uploads keep their true time.

The log is append-only.
Corrections (a teacher `override`, a human fix) are separate amendment rows; replay applies the latest amendment per (interaction, item).
Nothing in the log is updated in place or cascade-deleted.

### 4.6 Memory model (the "smarter score")

A plain counter ("answered correctly twice") ignores time and forgetting.
pauk uses a two-number memory model in the spirit of FSRS (free spaced repetition scheduler):

- Stability `S` (days): how long until recall probability drops to 90 %.

- Difficulty `D` (1–10): how hard this item is for this learner.

- Recall probability now: `R(t) = 1 / (1 + t / (9·S))`, with `t` = days since the item was last seen (so `R(S) = 0.9`).

The model is a pure function `step(state, event, model_version) → state`, applied per (item, interaction) in `(occurred_at, id)` order.
Each state row records the model version that produced it (`model = "pauk-mm@1"`).
States are a cache: a rebuild command recomputes all of them from the log, and an integration test asserts that "import a log, then rebuild" yields identical states.
That test is what keeps the claim honest, and it is what lets a better model (e.g. FSRS with fitted parameters) replace v1 later without losing anything.

The contract (`docs/api.md`) specifies only the outputs: `S`, `D`, `R`, the mastery level and the selection lists.
The v1 formulas below live in the PHP class and in `docs/architecture.md`, so retuning is not an API change.

v1, mode factor `m`: recognize 0.6, recall 1.0, produce 1.2, explain 1.0, self_report 0.5.

- First contact (no state yet):

  - `introduce` → `S = 0.2`, `D = 5`.
  - test → `S = 0.2` on fail, else `S = m · {hard: 1, good: 3, easy: 8}`; `D = {fail: 7, hard: 6, good: 5, easy: 3}`.

- Success (`hard`/`good`/`easy`) with current `R`:

  `S' = S · (1 + m · k · ((11 − D)/10) · S^−0.15 · (e^(2·(1 − R)) − 1))`, `k = {hard: 4, good: 10, easy: 16}`.

  At `R ≈ 1` (asked again within the same session) the growth factor is ≈ 1: repetition in one sitting consolidates the item for today but does not fake long-term stability.
  A success at `R = 0.9` roughly doubles `S`; a success after long overdue (`R = 0.5`) multiplies it several-fold.

- Failure: `S' = max(0.2, min(S/2, 0.5 + 0.1·S))`, `lapses += 1`.

- Difficulty after each test: `D' = clamp(0.9·(D + Δ) + 0.1·5, 1, 10)`, `Δ = {fail: +1, hard: +0.5, good: 0, easy: −0.5}`.

- `best_mode`: the strongest mode with a success so far (recognize < recall ≈ explain < produce).

### 4.7 Mastery level (what the learner sees)

The 0-to-5 score, derived from the state:

- 0 unseen: no state.

- 1 introduced: seen, never answered correctly (or `S < 0.5`).

- 2 fragile: `S < 3` days.

- 3 learning: `3 ≤ S < 21`.

- 4 known: `S ≥ 21`.

- 5 mastered: `S ≥ 90` and `best_mode` is at least `recall`.

The UI shows the level plus the current recall probability (`parlare — level 3, 84 %`).
A subject's coverage is `Σ priority·R / Σ priority` over its transitive item set: "you currently know about 41 % of the important Italian vocabulary".

### 4.8 Per-learner flags

- `status`: `active`, `focus` (the learner wants this now; double weight in selection), `suspended` (never offered).

- `note`: a short teacher-maintained memo about this learner and item ("confuses parlo/parla", "knows it from Spanish").
  This is what makes the teacher feel personal across sessions.

### 4.9 What to practise next (server-side selection)

`GET /profile/next` returns two ranked lists so every teacher behaves alike:

- `review`: items with a state, status not suspended, `R < 0.9` (or `lapses ≥ 2` and `R < 0.95`), ranked by `(0.9 − R) · (0.5 + priority/100) · (focus ? 2 : 1)`.

- `new`: unseen items whose `requires` prerequisites are all at level ≥ 3, ranked by priority (desc), then level (asc), then key.
  Empty once the session has reached the new-item cap (`tutor.new_items_per_15min`, pro rata); the host also refuses `introduce` of an unseen item beyond the cap.
  The cap is enforced in code, not left to the LLM.

Each entry carries the item, its state, and a `reason` (`"due: R=0.62"`, `"new: priority 95, A1"`).
This replaces nothing: `GET /quiz/cards` keeps its formula for card quizzes.

### 4.10 Avoiding near-duplicate items

Duplicates split the evidence for one piece of knowledge across two rows, so both look weaker than the learner is.
But whether two items denote the same thing is a judgement of meaning: "Park et al. 2006" in a flow-cytometry conversation and a DOI, "Bayes' rule" and "Bayes' theorem", "Gauss–Markov theorem" and "OLS is BLUE", `it/sbagliare` and "fare un errore" (related, not the same).
No string rule decides that, an LLM can.
And a wrong decision is cheap as long as it is visible and reversible: one item too many is merged later, a wrong merge is undone.

So the work is split by what each side is good at:

- The server finds candidates (deterministic, fast, high recall, no claim of sameness) and decides only exact identity.
- The LLM judges candidates and searches semantically.
- Every judgement is stored with its reason and author, never asked twice, and reversible.

#### Exact identity (server, no judgement needed)

- Same `space/key`, or a key or label that is an alias of an existing item → the existing item is returned (`{"created": false, "via": "key" | "alias"}`), idempotently.
- Same strong identifier (`attrs.doi`, `attrs.isbn`, `attrs.wikidata`) → the existing item is returned (`"via": "doi"`).

#### Candidates (server) and the judgement (LLM)

`norm(s)`, one function in PHP: strip Markdown and parentheticals, lowercase, fold diacritics with a fixed table (like `Text.php`), collapse non-alphanumeric runs to one space, trim.
Stored as `items.label_norm` and indexed, as is the generated `key_base` (key up to the first dot).

On every single-item create (`add-item`, `POST /items`, proposals) the server collects up to 10 candidates in the same space (and, for `concepts`, also across spaces by alias), any of:

- equal `label_norm` or `key_base` (except a form against its own lexeme);
- whole-word containment either way (`la farfalla` / `farfalla`, `park 2006` / `park 2006 flow cytometry gating`);
- alias match;
- substring match of the label in other items' labels, glosses and aliases;
- for long labels (≥ 8 characters, non-word kinds) Levenshtein ≤ 2 over a small prefiltered set.

If there are candidates, nothing is created yet; the response is 409 `possible_duplicates` with each candidate's ref, kind, label, gloss and the reason it matched.
The caller must then resend with an explicit decision covering every candidate:

- `same_as: REF` — it is that item: the new label is stored as an alias of it (with `origin` and reason), and the caller continues with the existing item;
- `distinct_from: [REF, ...]` plus a one-line `reason` — stored as a `related` link with the reason, so the pair is never flagged again and becomes a natural mc distractor.

The server cannot verify how well the LLM searched, but this protocol guarantees that it saw the obvious candidates and left a reason that a human or a later sweep can check.
Beyond that, the harness asks the teacher to search with its own queries before adding (synonyms, other languages, abbreviations, author + year, the DOI if it knows one); that is the part only the LLM can do.

#### Sweeps (LLM, after the fact)

Lexical candidates miss duplicates with entirely different names, and the teacher may judge wrongly in the moment.
A dedup sweep catches both:

- After every session, the post-session review (16.2) checks the items added or aliased in that session against their subject and space.
- `pauk items dedup [--dir D] [--space S] [--since DATE]` runs a full pass: an agent gets the items in batches (ref, kind, label, gloss, aliases, subjects; a few hundred per batch fit easily into one context), grouped by subject and kind, and returns merge proposals, each with a reason.
- After a bulk import, the import response names a ready `pauk items dedup --since <import time>`.

#### Merge and unmerge (reversible)

`POST /items/{a}/merge {"from": REF_b, "reason": "...", "by": "teacher" | "observer" | "human"}` in one transaction:

- b's `interaction_items` are repointed to a, keeping `origin_item_id = b` on each row (if one interaction touched both, a's row is kept so the event counts once, and b's outcome is kept as an annotation);
- b's card links, subject links and item links move to a (self-links dropped);
- both states are deleted and a's merged log is replayed in time order; S and D are never added or averaged, and close-together events replay at R ≈ 1, so a merge does not fake stability;
- `status` becomes focus if either was, suspended only if both were; differing notes are concatenated;
- a's fields win; b's key and label become aliases of a; b is archived with `merged_into = a`;
- the merge is recorded in `item_merges` (a, b, reason, by, session, time).

`POST /items/{b}/unmerge` reverses it: rows with `origin_item_id = b` move back, b's aliases on a are removed, b is unarchived, both logs are replayed.
Because the log is never rewritten, a merge is a reversible view of the evidence, not a destructive edit.

Who may merge is a setting (`tutor.merge`, 4.11): by default merge proposals from the teacher, the observer and sweeps appear on the profile page under "suggested merges" for one-click accept; with `free` the agents merge directly and the profile page lists "recent merges" with an Undo button.
Renaming a key (`PATCH key`) leaves the old key as an alias, which is needed when a second homograph sense appears.

#### Bulk imports

`PUT /items/bulk` resolves exact identity (key, alias, strong id) and upserts, without 409s (a lexicon has thousands of legitimate neighbours).
An item with `attrs.origin = "teacher"` and a different normalized gloss is not overwritten but reported as a conflict (a lexicon `pesca` = peach must not silently replace a learned `pesca` = fishing).
The card-to-item derivation script uses the same slug and norm functions, with shared test fixtures.

#### Not now

Embeddings: with the LLM as judge they would only improve candidate recall, at the price of a model in the client and vectors to keep consistent.
Revisit only if sweeps keep finding duplicates the lexical candidates missed.
Soundex (English-only) and InnoDB FULLTEXT (token size and stopwords not configurable on shared hosting) are not useful here.

### 4.11 User settings

Stored remotely in `user_settings` (one JSON value per name, defaults from a registry in code), edited in the web UI's settings panel, and delivered to the teacher in `pauk teach state`.
The teacher never changes stored settings; when the learner asks for something different in chat ("please speak English"), the teacher complies for the current session and points to the settings panel to make it permanent.

- `tutor.language`: language the teacher explains and gives feedback in, as a BCP 47 tag (default `de`).

- `tutor.immersion`: per language space, how much the teacher speaks the target language: `off`, `partial` (exercises and short phrases in the target language), `full` (everything except explanations of errors). Example: `{"it": "partial"}`. Default `off`.

- `tutor.item_creation`: whether the teacher may add items:

  - `off`: never; the teacher can talk about anything but records only existing items.
  - `propose` (default): the learner sees a proposal card (with any duplicate candidates) and the item is created only on Add.
  - `on_request`: created directly when the learner asked to learn it (the teacher's judgement, logged with the learner message it relied on), otherwise proposed.
  - `free`: the teacher creates items when it judges them useful.

  The duplicate protocol (4.10) applies in every mode.
  Teacher-created items carry `attrs.origin = "teacher"` and the session id; the profile page lists them under "recently added" with Undo (archive).

- `tutor.merge`: `propose` (default; merges suggested by teacher, observer or sweeps wait for one click on the profile page) or `free` (agents merge directly; "recent merges" with Undo).

- `tutor.new_items_per_15min`: new-item cap, enforced by selection and host (default 8).

- `review.after_session`, `review.auto_triage`: section 16.

Typical cases of a teacher adding an item:

- The learner asks "what is *Schmetterling* in Italian?"; `it/farfalla` is not in the profile.

- The learner writes "*ho andato*"; the profile lacks the rule that motion verbs take *essere* in the passato prossimo (`it/passato-prossimo-essere`), so the error cannot be recorded against anything.

- During a bakery role-play the baker says "*in bocca al lupo*", the learner asks what it means.

- Explaining FastRet, the learner stumbles over "retention time"; the teacher adds `concepts/retention-time` and links it into the subject the session is about.

- The learner mentions "the Park et al. 2006 gating paper"; the teacher searches (author + year, topic, DOI if known), finds nothing, and adds `concepts/park-2006-flow-cytometry-gating` with `attrs.doi` once confirmed.

- Unprompted: the teacher decides that `it/farfalla` should follow `it/ape` because both appeared in a story (only under `free`).

## 5. Relation to the existing card system (backwards compatibility)

Cards and directories stay exactly as they are; the knowledge layer is added beside them.

- Cards are exercises; items are knowledge. A new junction `card_items` links a card to the items it tests.

- Answering a linked card (`/answer`, `/self-grade`) keeps writing `reviews` as today and additionally writes an interaction with `source = card` for its items: mc/match → `recognize`, text/recall → `recall`; exact → `good`, typo → `hard`, wrong → `fail`.
  So the TUI quizzes feed the profile from day one.
  When a card is first linked, its past `reviews` are backfilled as interactions with their original `answered_at` as `occurred_at`.

- The teacher can use linked cards as a ready-made, deterministically graded exercise bank (`GET /items/{ref}/cards`).

- Quests are deprecated (issues/0009): the town scene (14) covers them, with the bakery, station and restaurant quests as its NPC goals.
  The quest card type, its endpoints and the TUI quest screen keep working for existing cards (the API never drops a documented endpoint), but no new quest content is written.

- All schema changes are additive migrations (008+), as the deploy process requires.

## 6. Designed for change

The local parts (session host, harness text, web UI, activities) carry no persistent contract and can be rewritten freely.
The expensive-to-reverse decisions are all in the remote schema and in the interaction log, because that is the only data that cannot be regenerated.
So the rules below concentrate there.

- Keep the raw evidence (4.5): exercise with key, raw response, grader version, true time.
  Anything derived (outcomes via re-grading, states, mastery, coverage) can then be recomputed by a future version.

- Append-only log, amendment rows, archive instead of delete, no cascades from items into the log.

- Versioned derivations: `model` on every state, `grader` on every interaction, plus the rebuild command and its replay test (4.6).

- Open value sets are VARCHAR validated by the API (`kind`, `rel`, `mode`, `source`, `best_mode`, `grader`), so adding a value is a code change, not a migration; `cards.type` needed four `ALTER ... ENUM` migrations already.
  ENUM only for closed sets (`outcome`, `status`).

- Compatibility rule, added to the Conventions of `docs/api.md`: clients ignore unknown fields; string fields with enumerated values may gain values; additive changes do not bump `/api/v1`.
  This single sentence is what keeps `/v1` stable without further versioning machinery.

- External identity is `space/key` for items and `uuid` for interactions everywhere outside the database (commands, import, export, transcripts), never numeric ids.

- Export as the escape hatch: `GET /export` / `pauk export` writes JSONL with a header line `{"format": "pauk-export", "version": 1}`, followed by items, aliases, links, card links, interactions with amendments, settings and session summaries, but no states.
  `pauk import` of such a file upserts by ref and uuid and then rebuilds states.
  Together with the replay test, this gives a way off IONOS, a way to restructure the schema ("export, migrate, re-import"), and a backup that is readable without MariaDB.

- One generic grader in PHP: `grade(kind, key, response) → outcome` behind one interface, with the exercise stored as JSON, so a new keyed exercise kind needs no migration.
  Teacher-graded kinds need only Python and JS.

- Local protocol: exercises, actions and events are Pydantic models in the host, which gives validation and `/openapi.json` for free; `pauk teach help --json` dumps the action schemas.
  The `pauk teach` wrappers and the harness text stay hand-written (about 15 thin commands; the harness is pedagogy, not schema).
  The harness ships in the same package as the host and is read at runtime via `instructions`, never copied into prompts or skills, so agent and host cannot drift apart.
  `attach` returns `{"protocol": N}` and `pauk teach` refuses a mismatch with "upgrade pauk" (the remaining risk: a stale `pauk` on PATH in manual mode).

- Settings are `(name, JSON value)` with a registry of defaults; new settings need no migration.

- Multi-user and sharing later: the `items` / `item_states` split already separates content from learner memory.

## 7. System architecture

    browser (learner)                 claude CLI (teacher)
          │  HTTP + SSE                     │  `pauk teach ...` (HTTP)
          ▼                                 ▼
    ┌───────────────── session host (local, `pauk`) ─────────────────┐
    │ serves web UI · holds transcript · validates teacher actions   │
    │ holds the API token · never computes scores                    │
    └──────────────────────────────┬─────────────────────────────────┘
                                   │ HTTPS, bearer token
                                   ▼
                  pauk API (IONOS, PHP + MariaDB): items, states,
                  interactions, grading, selection, settings, reports

- Session host: part of the Python CLI package (`pauk.tutor`), FastAPI + uvicorn, bound to 127.0.0.1 on a free port.
  It keeps the live transcript in memory and appends it to `~/.local/share/pauk/sessions/<id>.jsonl`.

- Secrets per session, each random 128-bit: a learner key (in the browser link), a teacher key (given to the agent), an observer key.
  None is the API token; the token never leaves the host.

- Web UI: buildless static files served by the host (vanilla JS or Preact via ESM, markdown and KaTeX via small libraries), SSE for server push.
  This is also the seed of the web client in issues/0004.

- Teacher transport: plain HTTP on the host, wrapped by the `pauk teach` subcommand (one subcommand per endpoint, JSON on stdout).
  A shell CLI works with any agent and makes the permission rule trivial (`Bash(pauk teach:*)`); an MCP adapter can be added later on the same endpoints.

- Grading of keyed exercises happens in the remote API (`POST /interactions` with the key and the response), reusing `api/src/Text.php`, so grading stays implemented exactly once.

## 8. Session lifecycle

1. `pauk` (no arguments) starts the host, creates a session, prints `Open http://127.0.0.1:8765/s/<id>#k=<learner-key>`, and spawns the teacher agent in the background (8.1).
   `pauk --no-agent` prints the teacher attach command instead, for running the teacher manually.
   The current TUI moves to `pauk tui`, frozen in the backlog (issues/0015); the Typer subcommands stay unchanged.

2. The agent attaches (`pauk teach attach`, protocol check), reads its instructions (`pauk teach instructions`), then blocks in `pauk teach wait`.

3. The learner opens the link and picks a goal on a start card: subject(s), mode (`learn new`, `review`, `mixed`, `free chat`), duration (default 15 min).
   Or just types a message.

4. Teacher and learner alternate (section 9).

5. The session ends when the learner clicks End, the duration is reached (the teacher wraps up), or the learner is idle for 10 minutes.
   The teacher posts a summary; the host stores it remotely (`tutor_sessions`), stops the agent, keeps serving the transcript read-only, and starts the post-session review if enabled (16.2).

### 8.1 Spawning the teacher

The host runs, with the session env set (`PAUK_SESSION=<host url>/s/<id>`, `PAUK_TEACHER_KEY=...`):

    claude -p "You are the teacher in a pauk tutor session. Run `pauk teach instructions` and follow them exactly until the session ends." \
        --allowedTools "Bash(pauk teach:*)" \
        --output-format stream-json

The agent's stdout goes to `~/.local/share/pauk/sessions/<id>.agent.log`.
The agent command is configurable (`[tutor] agent = ...` in the pauk config), so other agent CLIs can be plugged in.

Manual mode: in any Claude Code session the user says "connect to pauk chat <teacher-url> and take over the role of the teacher"; the teacher URL embeds the key, and `GET <teacher-url>` returns the same instructions with the exact `pauk teach --session <url>` invocation.

### 8.2 Robustness

- Only one teacher may be attached; a second `attach` gets 409 unless `--takeover`.

- If the agent process dies, the browser shows "teacher disconnected" with a Restart button; a new agent attaches and calls `pauk teach state`, which returns goal, transcript tail, open exercises and items touched so far, so it can continue seamlessly.

- `wait` returns after at most 90 s with `{"events": []}` (below the agent's tool timeout); the teacher simply waits again.

- Remote writes carry the interaction uuid; when the API is unreachable the host queues them and retries, idempotently.

## 9. Session protocol

All payloads are JSON.
Every transcript event has `seq` (monotonic), `at`, `from` (`teacher`, `learner`, `observer`, `system`) and `type`.
Teacher endpoints require `Authorization: Bearer <teacher-key>`, learner endpoints the learner key, observer endpoints the observer key.
Items are referenced as `space/key` throughout.

### 9.1 Exercise object

    {"id": "ex12",                      // assigned by the host
     "kind": "mc",                      // mc | match | text | open | recall
     "mode": "recognize",               // see 4.5
     "items": ["it/parlare"],           // items this exercise tests
     "prompt_md": "Which word means **to speak**?",
     "options": [{"id": "a", "text_md": "parlare"}, {"id": "b", "text_md": "partire"}],
     "correct": ["a"]}                  // hidden from the learner

Per kind:

- `mc`: `options` (2–6), `correct` (one or more option ids). Keyed.

- `match`: `pairs` of `{left_md, right_md}`; the browser shuffles the right side. Keyed.

- `text`: `accepted` (one or more accepted answers, graded with the API's normalization + typo tolerance). Keyed.

- `open`: free answer, `reference_md` optional (hidden); the teacher judges.

- `recall`: `reference_md` shown after the learner reveals it; the learner self-grades.

Optional on every kind: `card_id` (the exercise was taken from a linked card).
An exercise never carries outcomes; they come only from grading.

The host rejects an exercise (400) when `items` is empty, contains a ref not in the profile, a keyed kind has no key, or mc options do not contain the correct id.

### 9.2 Teacher actions (`pauk teach <cmd>`)

Reading:

- `instructions`: the teacher harness (section 10), as markdown.

- `help [--json]`: the action list with JSON schemas.

- `state`: session goal, user settings (4.11), elapsed time, new-item budget left, open exercises and activities, transcript tail (last 30 events), items touched with level before → now.

- `wait [--after SEQ]`: blocks until learner events arrive (max 90 s). Returns `{"events": [...], "last_seq": N}`.

- `profile [--dir D]`: per-subject counts by level, coverage, due count, recent lapses.

- `next --dir D [--n 10]`: the selection from 4.9.

- `items [--dir D] [--space S] [--q TEXT] [--level L] [--kind K]`: search over label, gloss, body and aliases.

- `item REF`: item with state, notes, links, last 10 interactions, linked cards.

Acting (each appears in the learner's chat):

- `say TEXT_MD`: a chat message (explanation, encouragement, small talk). Never evidence.

- `introduce REF [TEXT_MD]`: shows the item as an info card (label, gloss, body, image) and records an `introduce` interaction. Refused for unseen items beyond the new-item cap.

- `ask EXERCISE_JSON`: one exercise. Keyed kinds are graded instantly when answered (9.4).

- `drill EXERCISES_JSON`: 2–20 keyed exercises shown back to back with instant feedback, no teacher round-trip; the teacher gets one `drill_done` event with all results. This is the main tool for fast vocabulary rounds.

- `grade EXERCISE_ID --outcomes '{"it/parlare":"good","it/present-are":"fail"}' [--feedback TEXT_MD] [--note REF=TEXT]`: required for `open` exercises, records the interaction and shows the feedback.

- `override EXERCISE_ID --outcomes ... --reason TEXT`: corrects an automatic grade (e.g. an accepted synonym the key lacked); allowed once per exercise, shown to the learner, recorded as an amendment row.

- `hint EXERCISE_ID TEXT_MD`: a hint for an open exercise; caps its outcomes at `hard`.

- `note REF TEXT`: updates the per-learner item note (4.8).

- `focus REF` / `suspend REF`: only when the learner asks for it.

- `link REF DIR`: adds an existing item to a subject (e.g. `concepts/linear-regression` into `bioinformatics`).

- `merge A B --reason TEXT`: B is the same as A; under `tutor.merge = propose` this becomes a suggestion on the profile page, under `free` it is executed (reversible, 4.10).

- `add-item ITEM_JSON [--same-as REF | --distinct-from REF... --reason TEXT]`: adds a missing item to an existing space and links it into the session's subject, governed by `tutor.item_creation` (4.11) and the duplicate protocol (4.10): an exact hit returns the existing item; candidates return 409 until resent with `--same-as REF` or `--distinct-from REF... --reason`; then, by setting, it is refused (`off`), proposed to the learner (`propose`, answered later by `item_proposal_resolved`), or created.

- `report CATEGORY TEXT [--seq N]`: files a problem report (section 16), e.g. a missing action or a contradiction in the instructions.

- `end SUMMARY_MD`: closes the session.

There is deliberately no action to set a score, delete items, change stored settings, or edit interactions other than `override`.

### 9.3 Learner events (browser)

- `start`: `{dirs, mode, minutes}` from the start card.

- `message`: free text ("I don't get the difference", "let's switch to Greek").

- `answer`: `{exercise_id, selected | matches | text | self_grade}`.

- `item_proposal`: Use existing / Add / Add anyway / Edit / Dismiss on a proposed item.

- `dont_know`: gives up on an exercise (recorded as `fail` for keyed kinds; the teacher must grade open ones as `fail`).

- `hint_request`: asks for a hint on the open exercise.

- `report`: a problem report from the flag button (section 16); not forwarded to the teacher.

- `end`.

### 9.4 Events the teacher receives

- `learner_message`, `start`, `end`, `hint_request`, `item_proposal_resolved`, `settings_changed`, `activity_event`.

- `answered`: for keyed exercises `{exercise_id, response, outcome per item, correct_answer}` (already recorded and already shown to the learner); for `open`: `{exercise_id, response}` (awaiting `grade`); for `recall`: the self-grade (recorded).

- `drill_done`: list of `answered` payloads.

- `level_change`: item refs whose mastery level changed, with before/after.

- `time_warning`: two minutes before the chosen duration ends.

### 9.5 Browser UI

- Main column: the chat. Exercises render as widgets inline (option buttons, match columns, text input, reveal button), lock after answering, and show ✓/✗ with the correct answer.

- Composer: when an exercise is open the input submits the answer; a toggle sends a question to the teacher instead.
  Buttons: Hint, I don't know.

- Side panel: goal and timer, items touched this session with level arrows (`parlare 2 → 3`), subject coverage.

- Profile page (`/s/<id>/profile`): items per subject and space filterable by level, history per item, "recently added", "suggested merges" and "recent merges" with accept/undo, and the maintenance actions: edit, archive, rename key, merge, unmerge (4.10).

- Settings panel for 4.11 (written to the remote API, effective immediately).

- Problem reporting everywhere (16.1): a flag on every message, exercise and activity, plus "Report a problem" in the header.

- Markdown everywhere renders images, video and math (KaTeX for `$...$` / `$$...$$`).

- Activities (section 14) render inline in the chat or in a wide panel.

- Status line: "teacher is thinking…" while an answer awaits the teacher, "teacher disconnected" with Restart when the agent died.

## 10. Teacher harness (served by `pauk teach instructions`)

The text below is the normative behaviour of the teacher.
It is served verbatim, so it must stay short enough to read in one go.

> You are the teacher in a pauk tutor session.
> You talk to the learner only through `pauk teach` commands; your normal output is not shown to anyone.
> You never invent scores: you report what you observed, and pauk computes the memory state.
>
> Loop.
> Call `pauk teach state`.
> Then repeat: `pauk teach wait`, react to the events, act.
> If `wait` returns no events, call it again.
> Stop after `end` (yours or the learner's).
>
> Starting.
> If the learner has not chosen a goal, ask in one short message what they want (subject, learn new or review, how long).
> Read `pauk teach profile` and `pauk teach next` for the chosen subject.
>
> Choosing what to practise.
> Use `next`: work through `review` items first, and introduce `new` items while the learner succeeds.
> Aim for roughly 80 % correct answers: above 90 %, introduce new items or use harder modes; below 65 %, stop introducing, switch to easier modes, and revisit the failed items.
> pauk caps new items per session; when `next` returns no new items, stick to review.
> Prefer items flagged `focus`, and respect what the learner says they want.
>
> Teaching one item.
> A new item: `introduce` it, then test it with `recognize`, later `recall`, later `produce`.
> A known item: test it at its `best_mode` or one above.
> An item counts as consolidated for this session after two consecutive successes, the last one in `recall` mode or stronger.
> After a failure, give the correct answer with a one-sentence explanation, then test the item again after two or three other items, not immediately.
> Use at most 5 exercises per item per session; if it is still failing, write a `note` about the confusion and move on.
>
> Exercises.
> Prefer keyed exercises (`mc`, `match`, `text`): they are graded instantly and fairly.
> For runs of vocabulary use `drill` with 5–10 exercises.
> Use linked cards (`pauk teach item REF` lists them) when they fit.
> Build mc distractors from `related` items and items of the same kind and level, never from nonsense.
> Use `open` for explanations, sentences and papers; judge them only against the item's `gloss_md` and `body_md`, and say when the reference does not cover something.
> List in `items` exactly the items the answer gives evidence about: the target item, plus a rule or second word only if a wrong or right answer clearly reveals the learner's knowledge of it.
>
> Grading open answers.
> `good`: correct. `easy`: correct, instant and complete. `hard`: correct with errors that do not change the meaning, or after a hint. `fail`: wrong, missing, or "I don't know".
> Grade every answered `open` exercise exactly once, before asking the next question.
> If an automatic grade is clearly unfair (a valid synonym), use `override` with a reason; never override to be nice.
>
> Adding items.
> Only for something the profile lacks and the learner should learn, and only as `tutor.item_creation` allows.
> First search with `pauk teach items --q` several times: synonyms, other names (a theorem often has two), other languages, abbreviations, for papers author + year + topic and the DOI if you know it.
> Language-bound knowledge goes into its language space (`it`, `el`, ...), everything else into `concepts`; link the item into the session's subject.
> Do not invent keys for words, phrases and terms; send the label and let pauk derive the key.
> If pauk answers with candidates, decide for each one: `--same-as REF` when it is the same thing under another name or spelling (the new name becomes an alias), `--distinct-from REF` with a one-line reason when it is genuinely different (another sense, a related but distinct concept).
> When unsure, prefer `--same-as` for different names of one thing and `--distinct-from` for different things that share a name; a wrong call is cheap to fix later, a missing reason is not.
> Never record an error against a made-up item.
> If you notice two existing items that are the same, use `merge` with a reason.
>
> Talking.
> Write short messages in `tutor.language`, using the target language as much as `tutor.immersion` says for this language.
> If the learner asks for a different language in chat, comply for this session and mention that the settings panel makes it permanent.
> Answer learner questions directly; explanations are not exercises and are not recorded.
> If the learner says they already know something, ask one quick check question instead of taking it on trust; if they insist, record nothing and move on.
>
> Problems.
> If you need an action that does not exist, or these instructions contradict themselves or the situation, file `pauk teach report` and continue as well as you can; do not work around it silently.
>
> Ending.
> On `time_warning`, finish the current item.
> End with `end` and a summary: what was practised, what improved (level changes), what to review next time.

## 11. Remote API additions

Phase 1 is implemented; the authoritative contract is now docs/api.md, section "Knowledge profile", which differs from this sketch in details (items are addressed as `/items/{space}/{key}`, the bulk route is `PUT /items/bulk`, `/profile/next` takes a `new` limit set by the host instead of a session id, merge suggestions live under `/merges`).
Reports and tutor sessions follow in phase 2.

All endpoints are per user (bearer token), following the existing conventions (pagination, error shape, ISO timestamps) plus the compatibility rule from section 6.
`{ref}` in a path is `space/key` URL-encoded, or a numeric id.

Items:

- `GET /items?dir=&recursive=&space=&kind=&q=&level=&status=&mastery=&archived=`: list with state embedded.

- `GET /items/{ref}`: item + state + aliases + links + last 10 interactions + linked card ids.

- `POST /items`: create, with the duplicate check and `distinct_from` (4.10); key optional for word/phrase/term.

- `PATCH /items/{ref}`: edit fields; changing `key` leaves the old key as an alias.

- `POST /items/{ref}/archive`, `POST /items/{ref}/unarchive`. No hard delete.

- `POST /items/{ref}/merge` `{"from": REF, "reason", "by"}`, `POST /items/{ref}/unmerge`, `GET /merges?status=suggested` and `POST /merges/{id}/accept|dismiss` for suggestions (4.10).

- `PUT/DELETE /dirs/{id}/items/{ref}`: subject membership, idempotent like card membership.

- `PUT /items:bulk`: upsert up to 500 items by ref (aliases resolved) including links, with conflict and possible-duplicate lists in the response.

- `PUT /items/{ref}/state`: `status`, `note` only.

- `PUT/DELETE /cards/{id}/items/{ref}`: link a card to an item (first link backfills its reviews); `GET /items/{ref}/cards`.

Interactions:

- `POST /interactions`: `{uuid, occurred_at?, mode, source, session_id?, card_id?, exercise?, response?, prompt_md?, response_md?, feedback_md?, hinted?, items: [{ref, outcome?, note?}]}`.
  For keyed exercises the outcomes may be omitted: the API grades `exercise` against `response` with the generic grader, applies the outcome to every listed item, and stores the grader version.
  Idempotent on `uuid` (a retry returns the original result).
  Response: the grade (if any) and the new state + mastery level of every item.

- `POST /interactions/{uuid}/amendments` `{items: [{ref, outcome}], reason, by}`: appends an amendment; the affected items are replayed.

- `GET /interactions?item=&session_id=&since=`: history.

Profile, settings, sessions:

- `GET /profile?dir=`: counts per mastery level, coverage, due count, items with most lapses.

- `GET /profile/next?dir=&n=&session_id=`: section 4.9 (the session id lets the API apply the new-item cap).

- `GET /settings` (defaults filled in), `PATCH /settings` (unknown names or invalid values → 400).

- `POST /tutor-sessions` `{goal}` → id; `PATCH /tutor-sessions/{id}` `{ended_at, summary_md, teacher}`; `GET /tutor-sessions`.

Reports (section 16): `POST /reports`, `GET /reports?status=`, `PATCH /reports/{id}`.

Maintenance:

- `GET /export`: the JSONL export (section 6).

- `POST /admin/rebuild-states`: recompute all states from the log with the current model.

## 12. Schema (migrations 008+)

Phase 1 is `api/migrations/008_knowledge.sql`; `reports` and `tutor_sessions` come with phase 2.

Column lists abbreviated where they follow the existing conventions (BIGINT UNSIGNED ids, InnoDB, utf8mb4, FKs to `users`).

    CREATE TABLE items (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT UNSIGNED NOT NULL,
        space VARCHAR(16) NOT NULL,              -- it | el | de | en | concepts
        `key` VARCHAR(191) COLLATE utf8mb4_bin NOT NULL,
        key_base VARCHAR(191) AS (SUBSTRING_INDEX(`key`, '.', 1)) STORED,
        kind VARCHAR(32) NOT NULL,
        label_md VARCHAR(512) NOT NULL,
        label_norm VARCHAR(191) NOT NULL,
        gloss_md TEXT NOT NULL,
        body_md TEXT NOT NULL,
        attrs JSON NOT NULL,
        priority TINYINT UNSIGNED NOT NULL DEFAULT 50,
        level TINYINT UNSIGNED NULL,
        archived_at DATETIME NULL,
        merged_into BIGINT UNSIGNED NULL,       -- FK items
        doi VARCHAR(191) AS (JSON_VALUE(attrs, '$.doi')) STORED,
        created_at, updated_at,                  -- as in cards
        UNIQUE KEY uq_items (user_id, space, `key`),
        UNIQUE KEY uq_items_doi (user_id, doi),  -- likewise isbn, wikidata
        KEY idx_items_norm (user_id, space, label_norm),
        KEY idx_items_base (user_id, space, key_base)
    );

    CREATE TABLE item_aliases (
        user_id, space VARCHAR(16), alias VARCHAR(191) COLLATE utf8mb4_bin,
        label_md VARCHAR(512) NULL,              -- the alternate name as written
        item_id,                                 -- FK items
        origin VARCHAR(32), reason TEXT NULL, session_id NULL,
        created_at,
        PRIMARY KEY (user_id, space, alias)
    );

    CREATE TABLE item_links (
        from_id, to_id,                          -- FK items
        rel VARCHAR(32) NOT NULL,                -- form_of | requires | part_of | related
        note VARCHAR(255) NULL,                  -- e.g. the distinct_from reason
        PRIMARY KEY (from_id, to_id, rel)
    );

    CREATE TABLE item_states (
        user_id, item_id,                        -- PK (user_id, item_id)
        model VARCHAR(32) NOT NULL,              -- e.g. pauk-mm@1
        stability DOUBLE NOT NULL, difficulty DOUBLE NOT NULL,
        first_seen_at DATETIME(3) NOT NULL, last_seen_at DATETIME(3) NOT NULL,
        reps INT NOT NULL, lapses INT NOT NULL,
        best_mode VARCHAR(32) NULL,
        status ENUM('active', 'focus', 'suspended') NOT NULL DEFAULT 'active',
        note TEXT NOT NULL
    );

    CREATE TABLE interactions (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        uuid CHAR(36) NOT NULL UNIQUE,
        user_id, session_id NULL, card_id NULL,  -- FKs; card ON DELETE SET NULL
        source VARCHAR(32) NOT NULL,
        mode VARCHAR(32) NOT NULL,
        exercise JSON NULL, response JSON NULL, grader VARCHAR(32) NULL,
        prompt_md TEXT, response_md TEXT, feedback_md TEXT,
        hinted TINYINT(1) NOT NULL DEFAULT 0,
        occurred_at DATETIME(3) NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY (user_id, occurred_at)
    );

    CREATE TABLE interaction_items (
        interaction_id, item_id,                 -- PK; FKs without cascade
        origin_item_id,                          -- the item it was recorded against; differs after a merge
        outcome ENUM('fail', 'hard', 'good', 'easy') NULL,
        note TEXT NULL,
        KEY (item_id, interaction_id)
    );

    CREATE TABLE interaction_amendments (
        id, interaction_id, item_id,
        outcome ENUM('fail', 'hard', 'good', 'easy') NULL,
        reason TEXT NOT NULL, amended_by VARCHAR(32) NOT NULL,   -- teacher | human
        created_at
    );

    CREATE TABLE card_items (card_id, item_id, PRIMARY KEY (card_id, item_id));

    CREATE TABLE dir_items (dir_id, item_id, PRIMARY KEY (dir_id, item_id));   -- subjects

    CREATE TABLE item_merges (
        id, user_id, into_id, from_id,           -- FKs items
        status VARCHAR(32) NOT NULL,             -- suggested | done | dismissed | undone
        reason TEXT NOT NULL, suggested_by VARCHAR(32) NOT NULL, session_id NULL,
        created_at, decided_at NULL
    );

    CREATE TABLE user_settings (
        user_id, name VARCHAR(64) NOT NULL,      -- PK (user_id, name)
        value JSON NOT NULL,
        updated_at DATETIME NOT NULL
    );

    CREATE TABLE tutor_sessions (
        id, user_id, goal JSON, teacher VARCHAR(128),
        started_at, ended_at NULL, summary_md TEXT NULL
    );

    CREATE TABLE reports (
        id, user_id, session_id NULL, seq INT NULL,
        reporter VARCHAR(32) NOT NULL,           -- learner | teacher | observer
        category VARCHAR(32) NOT NULL,           -- bug | content | teacher | ux | idea
        text_md TEXT NOT NULL, context JSON NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'new',   -- new | triaged | closed
        issue_ref VARCHAR(255) NULL,
        created_at, updated_at
    );

`user_id` on `items` keeps the existing "every owned table carries user_id" rule; separating `items` (content) from `item_states` (learner memory) keeps a shared item catalog possible later without a rewrite.

Prerequisites to verify on IONOS before migration 008: the server's default utf8mb4 collation (MariaDB 11.5+ defaults to an accent-insensitive UCA collation, hence the explicit `utf8mb4_bin` on keys), generated-column support (MariaDB has it), and that no PHP extension beyond what `Text.php` already uses is needed.

## 13. Content

Item files live next to the card decks and are imported with the existing `pauk import` (detected by a top-level `items` key):

    {"space": "it", "dirs": ["italian/a1"],
     "items": [
       {"key": "parlare", "kind": "word", "label_md": "parlare",
        "gloss_md": "to speak", "body_md": "Regular -are verb. *Parlo italiano.*",
        "attrs": {"pos": "verb", "conjugation": "are", "freq_rank": 112, "cefr": "A1"},
        "priority": 59, "level": 1,
        "links": [{"rel": "requires", "to": "present-are"}]}
     ],
     "card_links": [{"card": "Translate to Italian: **to speak**", "item": "parlare"}]}

Seeding plan, all through the same slug/norm functions (4.10):

- derive items from the existing Greek and Italian decks (each translate card yields one item in `el` / `it` and a card link, backfilling its reviews), linked into the decks' existing directories as subjects;
- add a frequency-ranked Italian lexicon (priority from rank), importing it before teacher-added items accumulate;
- one `concepts` item per key concept and per paper of the PhD decks, with the recall answers as `body_md`, linked into the existing `phd/...` directories and into subject directories such as `statistics` or `immunology`; then one `pauk items dedup --space concepts` sweep, since the six decks overlap.

Activity content (town layouts, NPC specs, routes) stays bundled in the repository under `content/activities/` and ships with the client, like the autobahn graph today.
Reasons: it is coupled to the activity code (a town spec changes shape when the town module does, so both must change in one commit), it is the same for every user and not edited during sessions, git gives review and history, and CI can validate every content file against its activity module, as the existing test does for every `content/*.json`.
Cross-machine sync happens through `pip install` / `git pull` like the code.
What is per-user (progress, evidence) goes into interactions; only if worlds ever become user-authored or LLM-generated would they move into the database as JSON with a `spec_version`.

## 14. Activities (interactive exercises and mini-games)

Outline; a dedicated design doc precedes phase 4.

Beyond chat exercises, a session can run activities: a car on the autobahn map, labelling German states on a blank map, walking through a small town and talking to the baker, a derivation step by step.
They are what makes the browser worth it, and they are where the existing quest and route ideas move to.

### 14.1 Rules every activity must follow

- Fully API-controlled: the activity's state lives in the session host, and every change goes through one endpoint, `POST /s/<id>/activities/<aid>/act`.
  The browser uses exactly this endpoint for clicks and key presses, so anything a human can do, an agent can do, by construction.

- Fully inspectable without pixels: `observe(role)` returns the complete state as JSON plus a short text description sufficient to act ("You are at Nürnberg. Roads: A9 north to Leipzig (230 km), A3 west to Würzburg (110 km), ... Driven so far: 170 km.").
  LLM participants work on this, never on screenshots.

- Turn-based or event-driven: nothing depends on reaction time, so a participant that needs 10 seconds to think loses nothing.
  Walking in the town is click-to-walk or step-by-step, not real-time steering.

- Deterministic rules in code: kilometres, positions, collisions, what an object is called, whether a goal is reached.
  LLMs only produce language: NPC lines, narration, and judgements of free-text answers.

- Shared and role-filtered: every participant sees the same state, filtered per role (the learner does not see the answer key; teacher and observer do).
  Every action is a transcript event, so the observer and a restarted teacher can follow everything.

- Evidence-producing: objects, NPCs and goals carry item refs.
  When the learner names the oak *quercia* or orders *due cornetti*, the activity emits a graded event that becomes an interaction with `source = activity` (deterministic where the rule allows it, otherwise the teacher grades it like an `open` exercise).

### 14.2 Shape of an activity

An activity type is a pair of files under `cli/pauk/tutor/activities/<type>/`: a Python module (state, action schemas per role, rules, `observe`) and a JS module (browser renderer that sends the same actions).
A concrete instance is started from content in `content/activities/` (13).

Teacher commands: `activity start TYPE SPEC_REF`, `activity observe AID`, `activity act AID ACTION_JSON` (including NPC actions such as `{"npc": "baker", "say": "Buongiorno! Cosa desidera?"}`), `activity end AID`.
Learner actions arrive at the teacher as `activity_event`s via `wait`.

NPCs are played by the teacher, constrained by the NPC spec (persona, language, the items it should use, and "speak at most one level above the learner's level").
A separate NPC agent can come later if the teacher's context gets crowded.

### 14.3 First candidates

- Autobahn route: reuses `content/autobahn-graph.json` and `scripts/maps/render_route.py`. State: current node, path, km. Actions: `drive {to}`; free-text instructions ("I take the A9 to Leipzig") are parsed by the teacher into `drive` actions, as issues/0009 planned.

- Map labelling: click a region, pick or type its name. Keyed, graded deterministically, one item per state/city.

- Town scene: a tile map with objects and NPCs. Actions: `go_to {target}`, `inspect {target}`, `say {npc, text}`. Inspecting shows a picture and asks the learner to name it; talking is role-play graded by the teacher.

Rendered math needs no activity: KaTeX in every message covers it (9.5).

Each activity type is real development work; start with the autobahn route, whose data and renderer exist.

## 15. Observer role and simulated learners

Outline; detailed before phase 4.
Two principles hold from the start: the browser uses the same action endpoints as agents, and the host keeps a full JSONL transcript plus an audit log of every teacher command (including reads), so an observer can always be added after the fact.

### 15.1 Observer

The observer key gives a read-only view of everything: the transcript, hidden exercise keys, activity states, and the audit log, so the observer can see why the teacher chose what it did.

- Human observer: the browser view `/s/<id>/observe`, e.g. to watch two agents, or a real teacher watching a learner.

- Agent observer: `pauk observe state | wait | annotate SEQ TEXT [--tag T] | report CATEGORY TEXT [--seq N]`.
  Annotations attach to transcript events and are invisible to learner and teacher.
  Reports go into the `reports` table (section 16).

What an observer looks for: harness violations (grading inconsistently, skipping `grade`, ignoring settings, hammering one item, never introducing new items), dead ends (the learner wants to do something no action allows), ambiguous instructions, suspected duplicate items, and cost (teacher turns, latency, tokens per useful interaction).

The observer reports and suggests merges (which follow `tutor.merge`); it changes nothing else.

### 15.2 Simulated learners

`pauk learn` is the learner's counterpart of `pauk teach`: `state`, `wait`, `start`, `message`, `answer`, `hint`, `dont_know`, `activity observe|act`, `report`, `end`.
It calls exactly the endpoints the browser calls, so an LLM learner needs no Chrome at all; if it cannot accomplish something through `pauk learn`, the API is incomplete, which is itself a finding.

`pauk simulate --persona <file> --minutes 10` starts host, teacher, learner agent and observer agent together.
A persona states the learner's level, a profile snapshot (what they know), typical errors, and patience.

Limits, stated plainly:

- An LLM cannot really pretend not to know Italian; its "ignorance" leaks and it does not forget between sessions.
  Simulations therefore test the harness, the protocol and the games (does it run, does the teacher follow the rules, is every goal reachable, where does the learner get stuck), not whether people learn well.

- Simulations run only against a scratch database (`make serve`) with a throwaway user, never against the real profile, in line with docs/testing.md.

- Three agents cost three agents' worth of subscription quota; keep simulations short and occasional, e.g. before releasing a new activity.

Visual checks are a separate, optional layer: the observer may request a Playwright screenshot of the learner page at chosen events to spot rendering bugs.
Screenshots are for looking, never for playing.

## 16. Problem reports and triage

Problems surface while learning, so reporting must take one click from inside a session, and the report must carry enough context that nobody has to reconstruct what happened.

### 16.1 Reporting

- Every chat message, exercise and activity has a small flag button; the header has a general "Report a problem" button (shortcut `!`).
  Both open a short form: category, free text, and whether to attach the session context (on by default).

- Categories: `bug` (something broke), `content` (wrong gloss, bad distractor, duplicate item), `teacher` (the teacher misbehaved: unfair grading, ignored a setting), `ux` (confusing, missing affordance), `idea`.

- Attached context, collected by the host, not typed: session id, the flagged event's `seq`, the 20 surrounding transcript events (including hidden keys), referenced item refs, the activity state if any, host/API/harness/protocol versions, teacher agent command and model, browser user agent.

- Teacher, observer and simulated learners file reports through the same table (`pauk teach report`, `pauk observe report`, `pauk learn report`).

- Storage: remote table `reports`, via `POST /reports`; `pauk reports` lists them in the terminal, and the web UI has a reports page.

Why the database and not GitHub issues directly:

- The repo is public, and reports carry personal learning transcripts; they must not land on GitHub verbatim.

- The project tracks work in `issues/*.md`, not in GitHub issues.

- No GitHub token in the session host, and reporting works without `gh` auth.

Content reports are data problems, not code problems: a wrong gloss is fixed by editing the item.
The `content` form therefore offers "suggest a fix" (edited label or gloss, or "merge into ..."), applied by the learner with one click on the profile page, without triage.

### 16.2 Post-session review (automatic observer)

Watching a session live costs a third agent running `wait` loops for its whole length.
The same information is in the transcript afterwards, so the default is a single post-session pass:

- When a session ends and `review.after_session` is on (default on), the host starts one observer agent on the finished transcript (`pauk observe --session <id> --post`).

- It reads the transcript and the audit log once, checks them against the teacher harness, and files reports (reporter `observer`) for harness violations, dead ends, unfair grades and suspected duplicate items.

- Live observation stays available for simulations (15.2) and when explicitly requested.

### 16.3 Triage into issues

Turning a report into a proper issue needs the code, so triage runs in the repository, not in the session host:

- `pauk triage` (manual) or, when `review.auto_triage` is on and `[dev] repo` in the pauk config points to a checkout, automatically after the post-session review.

- It starts a Claude Code agent in the repo with read access to the code and to `pauk reports`, and write access restricted to `issues/` (`--allowedTools "Read Grep Glob Bash(pauk reports:*) Write(issues/**) Edit(issues/**)"`).

- Per report: work out what happened from the context, locate the responsible code or content, check `issues/` for an existing issue (append a dated note there rather than opening a duplicate), otherwise write a new `issues/NNNN-slug.md` with problem, evidence, suspected cause with file:line references, and a suggested fix.
  Then mark the report `triaged` with the issue reference.

- Privacy: paraphrase, never paste transcript text or personal answers into issue files (the repo is public).

- Triage commits on a branch `triage/YYYY-MM-DD` and never pushes, never touches code, never merges; the owner reviews the diff.
  Fixing stays a separate, deliberate step.

## 17. Phases

1. Done in API 0.10.0 / CLI 0.17.0 (issues/0014): knowledge layer in the API: migrations, items with identity and duplicate checks, aliases, merge, interactions with amendments, memory model with rebuild and replay test, selection, card links with backfill, settings, export.
   `pauk import` and `pauk export` for items.
   Cards answered in the existing TUI start feeding the profile without any TUI work.

2. Implemented on branch tutor-phase-2 (API 0.11.0 / CLI 0.18.0): session host, browser UI (chat, exercises, KaTeX, profile with merge suggestions, settings, problem reports), `pauk teach`, harness text, audit log; teacher attached manually with `pauk tutor --no-agent`.
   Tests drive the host with a scripted fake teacher, as the quest tests fake the provider.

3. Implemented on the same branch: auto-spawned agent, restart/resume, drills, session summaries; `pauk` without arguments starts the tutor, the TUI moved to `pauk tui` and is frozen (issues/0015).
   Pulled forward from phases 4–5: the observer role with the post-session review, `pauk items dedup` (the LLM sweep), `pauk triage`, `pauk learn` and `pauk simulate` (LLM teacher + LLM learner playing a persona + review; refuses non-local APIs unless `--allow-remote`, and marks its evidence `source: simulation`), and the activity framework with the autobahn route.

4. Activity design doc, activity framework and the autobahn route; observer role with post-session review; `pauk learn` and `pauk simulate`.

5. Map labelling and the town scene; automatic triage; retire quests; revisit the memory constants against the collected log.

## 18. Open questions

None at the moment.

Decided 2026-10-14: subjects grow on demand instead of being created up front.
The learner creates a subject (`pauk mkdir`) when they start working on it; the teacher only links items to subjects that exist (`pauk teach link`) and suggests a new one in chat when items keep falling outside every subject.
An empty `statistics` or `analytical-chemistry` tree would only clutter the start screen and the selection.
