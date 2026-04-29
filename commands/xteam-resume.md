---
description: "Resume an interrupted xTeam design session from its snapshot"
---

Resume a previously interrupted `/xteam-design` session.

If `$ARGUMENTS` is empty, list recent sessions under `.xteam/` and ask
which to resume.

Otherwise, load `.xteam/$ARGUMENTS/snapshot.json` and resume the
`xteam-design` skill from the phase recorded in the snapshot.
