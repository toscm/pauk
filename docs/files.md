# Files (pauk 2)

pauk 2 has no database and no server API of its own to speak of: everything it knows lives in plain text files.
This document is the contract for those files.
Change it first, then the code (`app/`).

There are two kinds of files:

- Knowledge files are written by people: YAML decks and Markdown items in source folders.
  pauk writes them only when an admin edits or adds an item or a folder in the app (`app/src/edit.ts`): it changes just that item in its deck, keeps the rest of the file as it was, and undoes any change that would add a problem `pauk check` reports.
  The app does not write Markdown items, cards, links or the decks that ship with pauk (`app/knowledge/`); those are edited in an editor.

- User files are written by pauk: the learning log, settings, transcripts and the API log of each user.

## Knowledge sources

A source is a folder (usually a git repository) listed under `sources` in `config.yaml`.
pauk reads the sources in order and builds one in-memory index; it re-reads them when a file changes.
The pauk repository's own `app/knowledge/` is always the first source (pauk explains itself there).
The repository's `examples/` (the Greek letters and a little Italian) is a source to try pauk with; a new `config.yaml` lists it.
Your own knowledge belongs in your own folders, usually private git repositories: the pauk repository is public and ships no other decks.

    pauk-content/
      pauk.yaml                  # manifest: format: 1, name (optional)
      italian/01-a1/03-verbs.yaml  # a deck: many items, each with cards
      physics/nmr/zeeman-effect.md   # one item: YAML frontmatter + Markdown body
      media/maps/de-bayern.png   # referenced as ![map](media/maps/de-bayern.png)

- Every `.yaml` / `.yml` file except `pauk.yaml` is a deck, every `.md` file except `README.md` is an item.
  Folders and files starting with `.`, and `media/`, are skipped.

- File and folder names are lowercase-kebab.

- A deck's path below the source root, without the extension, is its subject: `italian/a1/verbs.yaml` holds subject `italian/a1/verbs`, which lies inside `italian/a1` and `italian`.

- A number prefix gives the order in which subjects are meant to be learned: `italian/01-a1/03-verbs.yaml` is subject `italian/a1/verbs`, the 1st subject in `italian` and the 3rd in `italian/a1`.
  The prefix is not part of the subject, so renumbering never changes a subject (nor `also` lists, favorites or other sources that use the same folder without numbers).
  The app lists numbered subjects first, by number, then the others by name; the first source that numbers a subject wins.
  A Markdown item's subject is its folder.
  `also: [subject, ...]`, on a file or on one item, adds further subjects, so subjects still form a DAG.

- The app shows every subject as a folder, so the tree has two rules (`pauk check` warns when one is broken):
  - A subject holds either subfolders or items, never both: `x.yaml` never sits next to a folder `x/`, and `also` only names subjects without subfolders.
  - A subject holds at most 12 items (counting `also`); aim for 5 to 10, fewer for hard items.

- Media are referenced relative to the source root (`media/...`); pauk serves them under `/files/<n>/media/...`.

### A deck

```yaml
space: it                    # default space of the items below
also: [italian/core]         # optional, extra subjects for every item
items:
  - key: parlare             # required; space/key is the identity
    kind: word               # word form phrase rule symbol term fact paper skill other
    label: parlare           # Markdown
    gloss: to speak          # one line
    body: |                  # optional, longer Markdown
      Regular -are verb.
    priority: 90             # 0..100, default 50: what to introduce first
    level: 1                 # optional difficulty level
    mnemonic: "(de) ..."     # optional memory aid, shown when introduced
    anecdote: ...            # optional true story that makes it stick
    attrs: {pos: verb}       # optional, free-form
    aliases: [old-key]       # old keys (or space/key) that now mean this item
    requires: [present-are]  # links: key in the same space, or space/key
    part_of: []
    related: []
    also: [italian/a1]
    cards:                   # exercises for this item
      - {type: text, q: "Translate to Italian: **to speak**", answer: [parlare]}
      - {type: mc, q: "Which verb means *to speak*?", answer: [parlare], wrong: [partire, pensare]}
      - {type: match, q: "Match the forms", pairs: [[io, parlo], [tu, parli]]}
      - {type: recall, q: "Conjugate *parlare* in the present.", answer: "parlo, parli, parla, ..."}
      - {type: text, q: "...", answer: [...], items: [it/present-are]}   # also evidence for another item
cards: []                    # optional cards outside an item; they need `items`
```

- `answer` is the list of accepted answers (text), the correct options (mc, several allowed), or the reference (recall).

- Cards have no identity.
  Evidence belongs to items, and the log stores each exercise as it was shown, so editing or deleting a card never touches the history.

### A Markdown item

```markdown
---
space: concepts
key: zeeman-effect
kind: term
label: Zeeman effect
gloss: The splitting of spectral lines in a magnetic field.
cards:
  - {type: recall, q: "What is the Zeeman effect?", answer: "..."}
---
The body: as long as it needs to be.
```

### Keys

- A key is lowercase ASCII slugs separated by dots: `parlare`, `essere.pres.1sg`, `park-2006-flow-cytometry-gating`.

- A space is a short lowercase slug: one per language (`it`, `el`, `de`, `en`) for language-bound knowledge, `concepts` for everything else.
  Spaces only prevent false collisions (Italian *come* and English *come*); subjects say what something belongs to.

- `space/key` must be unique across all sources.
  Another source may add cards to an existing item through `items` on a top-level card, but never define the item again.

- A later source may extend an item instead: an entry with the same `space` and `key` and `extend: true` appends its `body` to the item's body and adds its `cards`, `also`, links and `aliases` (a `mnemonic` or `anecdote` only if the item has none).
  It does not move the item: the extending file's own subject does not count, only an explicit `also`.
  This is how private notes attach to public items: the private source extends, the public file stays as it is.

## Edit rules

The learning log refers to items by `space/key` and is never rewritten.
So knowledge files may change in every way that keeps keys meaningful:

- Free: wording, gloss, body, attributes, links, cards; moving, splitting or renaming files and folders; new items.

- Renaming a key: change it and put the old key into `aliases`.
  Old log lines resolve to the item through the alias.

- Merging two items: delete one and add its key to the other's `aliases`; the evidence of both now counts for one item.

- Splitting an item: the old key becomes an alias of the main successor; the other new items start without evidence.

- Deleting an item: allowed.
  Its evidence stays in the log, is ignored, and comes back if the key ever returns.

- Changing grading (fixing accepted answers): old answers keep the outcome they were graded with; the log records which grader judged them.

- Forbidden: reusing a key for a different meaning.
  It is the one rule no check can enforce, the same rule as never reusing a DOI.

`pauk check` validates all sources and prints problems as `file:line`.

### Versions

Knowledge needs no version numbers: not in the files, not in their names, and no commit hashes in the log.
The only version is the format version, `format: 1` in `pauk.yaml` and `config.yaml`.
It changes only when the syntax changes incompatibly, together with a migration script.

## User files

All in the pauk home (`~/pauk`, or `$PAUK_HOME`):

    ~/pauk/
      config.yaml                 # sources, users, teacher settings, prices
      logins.json                 # login cookies (private)
      .env                        # secrets, e.g. ANTHROPIC_API_KEY=... (private, optional)
      users/tobi/
        log/2026-10.jsonl         # the learning log, one file per month
        items.yaml                # items the teacher added (pauk appends; edit freely)
        settings.yaml             # language, new items per session, favorite subjects
        sessions/2026-10-29T14-03-11.jsonl   # chat transcripts, one event per line; their start events also rank recently used subjects first in Search
        api/2026-10.jsonl         # every Claude API call: usage, cost, with debug the full bodies
        reports.jsonl             # problems the teacher reported

### config.yaml

```yaml
format: 1
listen: 127.0.0.1:8765        # 0.0.0.0:8765 serves the LAN
sources: [~/Repos/pauk-content, ~/projects/my-project/pauk-cards]
teacher: {model: claude-opus-5-5, effort: medium, debug: true}
prices:                       # USD per million tokens: input, output, cache read, cache write
  claude-opus-5-5: [4, 20, 0.2, 5]
users:
  tobi: {password: "scrypt$...", admin: true, llm: true, budget: 20}
  guest: {password: "scrypt$...", llm: true, budget: 5}
```

- `pauk user add NAME [--admin] [--llm] [--budget USD]` writes a user entry.

- `llm` allows the Claude teacher; `budget` is USD per calendar month, after which only practice without a teacher works (no `budget`: no limit).

- The API key is not stored here but in `.env` (below).

### .env

Secrets, kept out of `config.yaml` so that file can be shown and shared.
Every `pauk` command reads it at startup with Node's `process.loadEnvFile`; a variable the shell already sets wins.

```sh
# Claude API key for the teacher, from https://platform.claude.com → Settings → API keys
ANTHROPIC_API_KEY=sk-ant-...
```

- One `KEY=value` per line, no `export`, no spaces around `=`; quotes are optional, `#` starts a comment.

- Today the only key is `ANTHROPIC_API_KEY`, which the Anthropic SDK reads.

- Private: `chmod 600 ~/pauk/.env`; never commit, paste or share it.

### The learning log

One JSON object per line, appended in time order, never edited.
Item states, flags and notes are recomputed from it at startup (the memory model `pauk-mm@1` folded over the lines in time order).

```json
{"id":"6fd7ffee96","t":"2026-10-29T14:24:11.180Z","type":"answer","session":"2026-10-29T14-24-00",
 "mode":"recognize","grader":"mc@1","items":{"el/alpha":"good"},
 "ex":{"kind":"mc","items":["el/alpha"],"prompt":"Which Greek letter is this: **α**?","options":["epsilon","alpha"],"correct":["alpha"]},
 "resp":{"selected":["alpha"]}}
```

- `id`: a random id, so amendments can refer to a line.

- `t`: ISO time in UTC with milliseconds; the month of `t` names the file.

- `type`:
  - `answer`: an answered exercise; `items` maps each ref to `fail`, `hard`, `good`, `easy`, or `null` (no evidence).
  - `introduce`: an item was presented (`items` with `null`); creates a state but tests nothing.
  - `amend`: corrects the outcomes of line `of`, with a `reason`; the original line stays.
  - `flag`: `item` gets `status` `focus`, `suspended` or `active`.
  - `note`: the teacher's memo `text` about `item`.

- `mode`: `recognize`, `recall`, `produce`, `explain` or `self_report`; it weighs the evidence.

- `grader`: `text@2`, `mc@1`, `match@1` (pauk), `teacher` (the LLM), `self` (the learner, recall cards), `gave_up` (explained before answering).

- `ex` and `resp`: the exercise as shown, with its key, and the response.
  They make every line self-contained: it stays meaningful whatever happens to the knowledge files.

Lines with unknown item refs are kept and ignored.
Sync is not part of version 1. Because the log is append-only, several devices could later each write their own log files (`log/<device>/...`) without ever conflicting, and the replay would sort all lines by `t`.

Compaction (not in version 1): older months may later be folded into one file per year, holding a checkpoint of every item's state (labelled with the memory model version) plus monthly counts per item.
The `type` field on every line is what makes that possible without a new format.
