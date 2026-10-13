# pauk triage instructions

You turn new problem reports into proper issue files in this pauk repository.
You may read the code, write only under `issues/`, and commit only on today's triage branch; you never push, never change code, never merge.

## Steps

1. `git status`: the work tree must be clean; if not, stop and say so.
2. `git switch -c <today's branch>` (or `git switch <branch>` if it exists).
3. Read `issues/README.md` (the issue convention) and list the existing issues (`ls issues`).
4. `pauk reports --status new` lists the reports; `pauk reports show ID` shows one with its session context (the surrounding transcript events, settings, versions).
5. For each report:
   - Work out what happened from the context.
   - Locate the responsible code or content with Grep/Glob/Read (`api/`, `cli/pauk/`, `content/`, `docs/`).
   - If an existing issue covers it, append a dated note there (`YYYY-MM-DD: ...`, one sentence per line) instead of opening a new one.
   - Otherwise write `issues/NNNN-short-slug.md` with the next free number, frontmatter `status: open` and the fitting `kind`, then: problem, evidence (paraphrased), suspected cause with `file:line` references, suggested fix.
   - `pauk reports mark ID --status triaged --issue issues/NNNN-....md`.
   - Ideas that are not problems become `kind: feature` issues; reports that are not actionable are marked `closed` with a one-line reason appended to an existing catch-all issue only if one exists, otherwise just marked closed.
6. Privacy: the repository is public. Paraphrase; never paste transcript text, learner answers or personal content into issue files.
7. Commit the new and changed issue files in one commit (`git add issues/...`, `git commit -m "triage: ..."`) and finish with a short list of what you did.
