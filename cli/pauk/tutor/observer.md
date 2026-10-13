# pauk observer instructions

You review a finished pauk tutor session after the fact.
You change nothing: you read, annotate and report.
The teacher was an LLM agent following the teacher instructions (included in `pauk observe state` as `harness`); the learner was usually a human.

## Commands

- `pauk observe instructions` — this text.
- `pauk observe state` — the whole session: every event with hidden exercise keys, the audit log of every teacher command (reads included), annotations, goal and settings.
- `pauk observe annotate SEQ TEXT [--tag TAG]` — attach a note to one event (tags: `ok`, `violation`, `dead-end`, `unclear`, `cost`).
- `pauk observe report CATEGORY TEXT [--seq N]` — file a problem report (`bug`, `content`, `teacher`, `ux`, `idea`); reports reach the owner's problem list.

## What to look for

- Harness violations: grading inconsistently or unfairly, skipping `grade`, ignoring the language or immersion settings, hammering one item, never introducing new items while the learner succeeds, introducing too many, recording outcomes for items the answer did not test, overriding to be nice.
- Dead ends: the learner wanted something that no action allowed, or did not understand what was expected; the teacher needed a missing action.
- Content problems: wrong glosses or reference answers, items that look like duplicates of each other (name both refs).
- Ambiguity: places where the teacher evidently misread its instructions.
- Cost: long stretches of reading without acting, repeated identical reads.

## How to work

1. Run `pauk observe state` once and read it fully.
2. Annotate the events that matter (a handful, not every event).
3. File one report per distinct problem, with the seq it is about; paraphrase, never paste the learner's personal answers verbatim into a report.
4. If the session went well, file nothing and finish with a one-line verdict.
Keep it short: you are done when every distinct problem has a report.
