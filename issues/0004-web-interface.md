---
status: wontfix
kind: feature
---

# Web interface

Static SPA served from the webspace, using the same API.
Framework decision pending (leaning to something buildless
or light: Preact/Vue + Vite). Must render question markdown
incl. images/video and support quiz + editing flows.
Prerequisite: issues/0001.

2026-10-14: Superseded.
The owner decided against a hosted web UI (docs/tutor.md, issues/0014): the UI assumes a capable local LLM, so it is served by the local session host that `pauk` starts, not from the webspace.
That browser UI (cli/pauk/tutor/static, vanilla ES modules, no build step) renders markdown with images, math and activities.
Card editing stays in the CLI (`pauk edit`, issues/0002).
