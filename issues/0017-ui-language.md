---
status: open
kind: feature
---

# Browser UI strings follow tutor.language

The teacher speaks the learner's `tutor.language`, but the fixed strings of the browser UI and of the activities ("what is it called?", "✗ it is latte", button labels, task headings) are English.
Found by the observer in a `pauk simulate` run of the Italian town (2026-10-14) with `tutor.language = de`.

Proposal: a small message table per UI language in `cli/pauk/tutor/static/` (English and German first), chosen from `tutor.language`; activity modules return message ids plus parameters instead of English sentences for learner-facing text, so the browser renders them in the learner's language.
Content in the target language (Italian object names, NPC lines) is unaffected.
