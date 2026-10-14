---
status: done
kind: feature
---

# Browser UI strings follow tutor.language

The teacher speaks the learner's `tutor.language`, but the fixed strings of the browser UI and of the activities ("what is it called?", "✗ it is latte", button labels, task headings) are English.
Found by the observer in a `pauk simulate` run of the Italian town (2026-10-14) with `tutor.language = de`.

Proposal: a small message table per UI language in `cli/pauk/tutor/static/` (English and German first), chosen from `tutor.language`; activity modules return message ids plus parameters instead of English sentences for learner-facing text, so the browser renders them in the learner's language.
Content in the target language (Italian object names, NPC lines) is unaffected.

2026-10-14: Done.
The browser has message catalogues in `cli/pauk/tutor/static/i18n/` (`en.js`, `de.js`; Italian or Greek is one more file), loaded by `i18n.js` from the primary subtag of `tutor.language` with English as the fallback, and re-renders everything when the setting changes.
Activity summaries are `Msg` objects (`activities/common.py`): the English text for agents plus an id and parameters, sent to the learner as `summary_msg`.
Content texts for the learner (`prompt_md`, town hints, goal `task_md`) may be translations (`{"en": "...", "de": "..."}`); the bundled italian-town, germany-states and germany-cities content has German.
`describe()` for agents stays English.
Error messages from the host (400s on invalid activity actions) are still English; the UI rarely triggers them.
Tests: `cli/tests/test_i18n.py` (catalogue completeness against the ids in the JS modules and the activity modules, the setting reaching the browser, translations in content).
