---
description: "Write approved KB diffs back to the knowledge base"
---

Retry a failed or deferred KB writeback for a completed xTeam session.

If `$ARGUMENTS` is empty, ask for a session-id.

Otherwise, load the `kb-diff.md` from the session's output directory
and present each candidate update for human approval. Approved items
are written to KB via MCP (M2: fixture echo only; live MCP in M3).
