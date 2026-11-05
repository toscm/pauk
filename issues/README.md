# Issue tracking

Issues live in this directory as markdown files, one file
per issue, versioned with the code they describe.

## Convention

- Filename: `NNNN-short-slug.md`, numbered sequentially.
  Numbers are never reused; renaming the slug is fine.

- Each file starts with frontmatter:

      ---
      status: open | in-progress | done | wontfix
      kind: feature | bug | question | task
      ---

- Body: a short problem/goal statement, then whatever is
  useful (acceptance criteria, findings, decisions). Append
  progress notes with dates instead of rewriting history.

- Closing an issue = setting `status: done` (or `wontfix`
  with a reason) in the same commit as the fix. Don't delete
  files of closed issues.

- Cross-reference issues as `issues/NNNN` in docs, commit
  messages, and other issues.

## Current index

Regenerate with `grep -H "^status:" issues/*.md`; no manual
index is maintained here.
