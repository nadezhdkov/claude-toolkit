---
description: A feature left half done by an earlier session, resumed in a fresh one. Measures whether the new session finishes it without losing the earlier decisions.
plugins: ["../../../plugin"]
runs: 3
max_turns: 30
timeout_seconds: 600
allowed_tools: [Bash, Read, Edit, Write, Grep, Glob, Skill]
tags: [continuity, relay]
env: { CTK_RELAY: "1" }
---

Continue the work from where the last session stopped.
