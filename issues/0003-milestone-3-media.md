---
status: done
kind: task
---

# Milestone 3: Media upload

- POST/GET/DELETE /media per docs/api.md (sha256 dedup, mime
  whitelist, 50 MB cap, 409 on deleting referenced media)
- static serving from media/ with long-lived cache headers
- CLI: `pauk media add <file>` printing the markdown snippet
- delete-protection check + tests

2026-09-09 (API 0.3.0 / CLI 0.5.0): Done. POST/GET/DELETE
/media with sha256 dedup, MIME whitelist, 50 MB cap, and
409 delete-protection when a card references the file. CLI
media add/ls/rm; importer resolves media:<path> references by
uploading and substituting the URL. TUI renders images inline
(textual-image, half-cell fallback). Germany maps live in
production (16 state maps served over HTTPS). Deferred to
issues/0006: media is public (unguessable hash only).
