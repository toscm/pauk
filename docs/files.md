# Files (pauk 2)

pauk 2 has no database and no server API of its own to speak of: everything it knows lives in plain text files.
This document is the contract for those files.
Change it first, then the code (`app/`).

There are two kinds of files:

- Knowledge files are written by people: YAML decks and Markdown items in source folders.
  pauk writes them only when an admin edits or adds an item or a folder in the app (`app/src/edit.ts`): it changes just that item in its deck, keeps the rest of the file as it was, and undoes any change that would add a problem `pauk check` reports.
  The app does not write Markdown items, cards, links or the decks that ship with pauk (`app/knowledge/`); those are edited in an editor.

- User files are written by pauk: the learning log, settings, transcripts and the API log of each user.
  The users' learning data can live in its own folder, a git repository that pauk syncs between devices (see [Progress and sync](#progress-and-sync)).

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

In the pauk home (`~/pauk`, or `$PAUK_HOME`), the files of this machine:

    ~/pauk/
      config.yaml                 # sources, teacher settings, prices, progress folder: nothing secret, shareable
      secrets.yaml                # the API key and the users' logins (private, never shared)
      logins.json                 # login cookies (private)
      api/tobi/2026-10.jsonl      # every Claude API call: usage, cost, with debug the full bodies

In the progress folder (`progress` in `config.yaml`, by default `users/` in the pauk home), one folder per user:

    users/tobi/
      log/macbook/2026-10.jsonl   # the learning log, one folder per device, one file per month
      items.yaml                  # items the teacher added (pauk appends; edit freely)
      settings.yaml               # language, new items per session, favorite subjects
      sessions/2026-10-29T14-03-11.jsonl   # chat transcripts, one event per line; their start events also rank recently used subjects first in Search
      reports.jsonl               # problems the teacher reported

The API log stays in the pauk home: it is large (with `teacher.debug` it holds every request in full) and belongs to the machine that made the calls.
pauk moves an `api/` folder it finds in a user's folder (from earlier versions) there.

### config.yaml

```yaml
format: 1
listen: 127.0.0.1:8642        # 0.0.0.0:8642 serves the LAN
sources: [~/repos/pauk-content, ~/projects/my-project/pauk-cards]
teacher: {model: claude-opus-5-5, effort: medium, debug: true}
prices:                       # USD per million tokens: input, output, cache read, cache write
  claude-opus-5-5: [4, 20, 0.2, 5]
progress: ~/repos/pauk-progress   # optional, default users/ in the pauk home
device: macbook               # optional, default the host name
```

- `config.yaml` holds nothing secret, so it can be shown, shared and kept in a (dotfiles) repository that links the same file on every machine.
  Paths starting with `~/` work on every system; on macOS and Windows, `~/repos` and `~/Repos` are the same folder.

- `progress`: the folder with one folder per user; a git repository there is synced (below).

- `device`: this machine's name in the log (`log/<device>/`); lower case letters, digits and `-` (others become `-`).
  Leave it out of a shared `config.yaml`: the host name differs per machine by itself.

### secrets.yaml

The secrets of this machine: the API key and the logins.
pauk creates it with a placeholder key; it is private (`chmod 600`), and never committed, copied or shared.

```yaml
anthropic_api_key: sk-ant-...   # from https://platform.claude.com → Settings → API keys
users:
  tobi: {password: "scrypt$...", admin: true, llm: true, budget: 20}
  guest: {password: "scrypt$...", llm: true, budget: 5}
```

- `anthropic_api_key`: the Claude API key for the teacher; `ANTHROPIC_API_KEY` set in the shell wins over it.

- `users`: written by `pauk user add NAME [--admin] [--llm] [--budget USD]` (it asks for the password and stores a salted scrypt hash).
  Each machine has its own logins, so a new machine needs one `pauk user add`.

- `llm` allows the Claude teacher; `budget` is USD per calendar month, after which only practice without a teacher works (no `budget`: no limit).
  The budget counts the calls of this machine (its `api/` folder), since API logs are not synced.

- Earlier versions kept the users in `config.yaml` and the key in `.env`; pauk moves both into `secrets.yaml` on its first start after the update and deletes `.env`.

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

Each device appends only to its own folder `log/<device>/`, so copies of the log on several devices never conflict.
pauk reads the files of all device folders (and files directly in `log/`, written before there were device folders) and sorts all lines by `t`.

## Progress and sync

The progress folder (`progress` in `config.yaml`) holds the users' learning data.
To share it between devices, make it a clone of a private git repository, e.g. `github.com/<you>/pauk-progress`, and point `progress` to it on every device.
There is no switch: pauk syncs the folder when it is the top of a git repository (it has a `.git`).

- pauk commits what it wrote, and if the branch has an upstream it pulls (with rebase) and pushes.
  In a fresh clone of an empty repository, the first sync pushes and sets the upstream.

- When: at `pauk start`, before and after each session, every 5 minutes while pauk runs, and when pauk is stopped (Ctrl+C, the login service).
  `pauk sync` does the same by hand.

- Commit messages name the reason and the device, e.g. `session 2026-11-12T08-30-00: tobi (macbook)`.

- No conflicts: every device writes its own log folder; pauk writes a `.gitattributes` that merges the other append-only files (`*.jsonl`, `items.yaml`) by keeping the lines of both sides and keeps LF line endings on every system; for anything else (`settings.yaml`) the device that syncs last wins.

- If a sync fails (offline, no access), pauk prints why and goes on; the next sync catches up.
  git must not ask for a password: use an SSH key or a credential helper.

- After changes of other devices arrived, pauk reads a user's files again, unless that user is in a session (then after it).

Not synced by pauk, since they belong to one machine: `secrets.yaml`, `logins.json` and the API logs in the pauk home.
`config.yaml` is not synced by pauk either, but it can be shared through a dotfiles repository (it holds nothing secret).

Compaction (not in version 1): older months may later be folded into one file per year, holding a checkpoint of every item's state (labelled with the memory model version) plus monthly counts per item.
The `type` field on every line is what makes that possible without a new format.
