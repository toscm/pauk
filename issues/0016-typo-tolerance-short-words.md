---
status: open
kind: question
---

# Typo tolerance accepts different short words

Text answers allow one edit for accepted answers of 4 to 15 characters (docs/api.md, "Answering").
In Italian a single changed vowel is often a different word or form: `faro` (lighthouse) was accepted as a typo for `fare`, `como` (Spanish) for `come`.
Found by the simulated learner and the teacher in a `pauk simulate` run (2026-10-13), both independently.

Options:

- Raise the no-typo threshold from 4 to 6 characters (simple; also affects card quizzes).
- Never count a change of the final vowel as a typo (language-specific, needs a rule per space).
- Keep the rule and let the teacher `override` such cases (already possible, but the learner never sees the near-miss).

Whatever is chosen, the result should tell the learner about a near-miss ("almost: *fare*, not *faro*") instead of silently accepting it.
Needs a decision before changing the documented grading.
