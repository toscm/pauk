---
status: done
kind: feature
---

# New session, teacher model, quieter composer

Feedback from the user after an "italian · learn" session (2026-10-15):

- After the end there was no way back to the start card short of restarting `pauk tutor`.

- The teacher (Opus 5.5) felt slow; Sonnet should be enough for language practice.
  In that session the teacher took 7 s (median) and 13 s (mean) to respond, at most 47 s.

- The composer at the bottom was never used and too prominent.

- The side panel should show more of the current configuration, in particular the model of the connected teacher.

2026-10-15: Done (API 0.13.0, CLI 0.21.0).

- `pauk tutor` serves sessions in a row: a finished session shows "New session", which starts the next session with a new teacher in the same process and opens its start card (`POST learner/new-session`, `launch.Host`).

- New setting `tutor.model` (default `sonnet`), passed to the agent CLI as `--model` (`{model}` in custom agent command lines); the settings dialog offers Sonnet, Opus and Haiku, and a change restarts a running teacher.
  The host reads the model the agent really runs on from claude's stream-json init line (`claude-sonnet-5-5`) and reports it in the status.

- The composer is only for free messages to the teacher now (tasks have their own inputs), closed by default and opened with "Write to the teacher" in the header; conversation mode opens it, and the learner's choice is remembered.

- The side panel shows the teacher's status and model and a configuration summary (model, language, immersion, new-item cap) with a link to the settings.

Checked in Edge against `pauk tutor --fake`, and with a real teacher agent (`claude-sonnet-5-5` reported).
