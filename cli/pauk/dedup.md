# pauk duplicate sweep instructions

You look for knowledge items that denote the same thing under different names, in the learner's pauk profile.
You only suggest merges; the learner decides.

## Commands

- `pauk items list --json [--space SPACE] [--dir PATH] [--kind KIND]` — items with ref, kind, label, gloss.
- `pauk items show REF` — one item with aliases, body, links (`related` links with a note mean someone already decided the pair is distinct).
- `pauk items merges --status suggested` and `--status dismissed` — what was already suggested or rejected.
- `pauk items suggest-merge INTO FROM --reason TEXT` — suggest that FROM is the same as INTO.

## How to work

1. List the spaces you will check: `concepts` first, then each language space (`it`, `el`, ...).
2. For each space, list the items (per subject directory if the space is large) and compare labels and glosses with your own knowledge: synonyms, abbreviations vs full names, two names of one theorem, the same paper cited differently, singular vs plural, the same word with and without article.
3. Before suggesting, `show` both items: skip pairs already linked `related` or already dismissed, and pairs that are related but genuinely different (a method and its variant, two senses of a word, a lexeme and its irregular form).
4. Suggest INTO = the item with the clearer canonical name (or the one with more evidence), FROM = the other, with a one-line reason.
5. Be conservative: a missed duplicate costs little, a wrong suggestion costs the learner's attention.

Finish with one line: how many items you checked and how many merges you suggested.
