# pauk triage instructions

You turn new problem reports into proper issue files in this pauk repository.
You may read the code and write only under `issues/`; pauk has already switched to today's triage branch and commits your issue files when you are done.

## Steps

1. Read `issues/README.md` (the issue convention) and list the existing issues (Glob `issues/*.md`).
2. `pauk reports --status new` lists the reports; `pauk reports show ID` shows one with its session context (the surrounding transcript events, settings, versions).
3. For each report:
   - Work out what happened from the context.
   - Locate the responsible code or content with Grep/Glob/Read (`api/`, `cli/pauk/`, `content/`, `docs/`).
   - If an existing issue covers it, append a dated note there (`YYYY-MM-DD: ...`, one sentence per line) instead of opening a new one.
   - Otherwise write `issues/NNNN-short-slug.md` with the next free number, frontmatter `status: open` and the fitting `kind`, then: problem, evidence (paraphrased), suspected cause with `file:line` references, suggested fix.
   - `pauk reports mark ID --status triaged --issue issues/NNNN-....md`.
   - Ideas that are not problems become `kind: feature` issues; reports that are not actionable are marked `closed` with a one-line reason appended to an existing catch-all issue only if one exists, otherwise just marked closed.
4. Privacy: the repository is public. Paraphrase; never paste transcript text, learner answers or personal content into issue files.
5. Finish with a short list of what you did (pauk commits the files).
