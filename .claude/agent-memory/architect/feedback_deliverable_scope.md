---
name: deliverable-scope-faultline
description: In Faultline, the user limits architect output to specific files, keeps spec.md byte-for-byte unchanged, and wants gaps reported in the reply
metadata:
  type: feedback
---

Write only the files explicitly requested (so far docs/tasks.md and docs/api.md). Never modify docs/spec.md. Don't create architecture.md or ADRs unless asked, because the spec already covers the design. Put the spec review (G-list), summaries, and decision-blocking analysis in the final reply.

**Why:** The user treats spec.md as the controlled requirements document and wants proposed changes flagged for approval, not applied.
**How to apply:** Mark any deviation as "(assumption, see Gx)" or "proposed, pending approval". Keep tasks in their spec milestone and describe re-sequencing in "Sequencing notes" rather than reordering.
