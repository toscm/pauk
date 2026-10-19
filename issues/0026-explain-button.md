---
status: done
kind: feature
---

# Explain button for exercises and drill questions

Feedback from the user (2026-10-19): next to "Abschicken", "Tipp" and "Weiß ich nicht", exercises should offer "Erklären": the teacher explains the topic once more, with a mnemonic (Eselsbrücke) where one exists.
It should also work after answering, e.g. after a correct answer that was only vaguely remembered, and for earlier questions of a drill.

2026-10-19: Done.

- Every exercise has an "Erklären" button that stays usable after answering (once per exercise).
  It sends `explain_request`; the teacher answers with `pauk teach explain EXERCISE_ID TEXT`, which appears in the chat as an `explanation` headed by the question.

- Before answering, Erklären gives up first (recorded like "Weiß ich nicht"), because the explanation contains the answer.
  Afterwards the recorded evidence stays as it is; the teacher is told to ask that item again later in the session.

- Drill dots of answered questions are buttons that go back to the question, with a link back to the current one; the drill summary has an Erklären button per question.

- The teacher instructions (harness.md, "Explaining") ask for the rule, the reason, one example, the contrast to the learner's mistake, and a well-known mnemonic or a self-made one marked as such.
