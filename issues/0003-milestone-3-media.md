---
status: open
kind: task
---

# Milestone 3: Media upload

- POST/GET/DELETE /media per docs/api.md (sha256 dedup, mime
  whitelist, 50 MB cap, 409 on deleting referenced media)
- static serving from media/ with long-lived cache headers
- CLI: `pauk media add <file>` printing the markdown snippet
- delete-protection check + tests
