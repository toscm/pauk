---
status: wontfix
kind: question
---

# Media files are publicly reachable

Media is served statically without auth; secrecy rests on
the unguessable sha256 filename. Fine for a personal app,
not fine if pauk becomes multi-user with private content.
Options: signed URLs, PHP-fronted media delivery (loses
Apache efficiency), or accepting the status quo. Decide
before any multi-user rollout.

2026-10-14: Accepted for now.
pauk has a single user, and the media are maps and illustrations, nothing private; the sha256 names cannot be guessed or listed.
Signed URLs or PHP-fronted delivery would cost complexity and caching for no current benefit.
Reopen before pauk gets a second user or private media (the trigger is in docs/architecture.md, "Decisions").
