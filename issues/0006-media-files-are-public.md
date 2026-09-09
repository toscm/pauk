---
status: open
kind: question
---

# Media files are publicly reachable

Media is served statically without auth; secrecy rests on
the unguessable sha256 filename. Fine for a personal app,
not fine if pauk becomes multi-user with private content.
Options: signed URLs, PHP-fronted media delivery (loses
Apache efficiency), or accepting the status quo. Decide
before any multi-user rollout.
