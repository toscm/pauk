---
status: done
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

2026-10-13: Second simulation: `por favore` was accepted as a typo for `per favore` (Spanish interference) without any hint to the learner.

2026-10-14: Decided and implemented (grader `text@2`): replacing a vowel by another vowel counts as two edits.
Words and phrases shorter than 16 characters get a one-edit budget, so a vowel swap there is never a typo (`faro`/`fare`, `como`/`come`, `por favore`/`per favore`, Greek `καλο`/`καλά`); dropped, doubled or wrong consonants and dropped vowels still are.
Longer answers (16+ characters, two edits) tolerate one vowel swap, which keeps long phrases forgiving.
This one rule covers every space without a per-language table, and since the swap now grades as wrong, the learner sees the expected answer ("Not quite" plus the reference) instead of a silent pass.
It applies to card quizzes too (docs/api.md, "Answering").
