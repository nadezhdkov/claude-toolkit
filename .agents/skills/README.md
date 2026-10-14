# Agent skills

A mirror of the skills of this repository for agents other than Claude Code (the open
`SKILL.md` layout). **Do not edit it**: change the source in `plugin/skills/` or `.claude/skills/` and run
`make skills`; CI fails when the mirror is out of date.

The skills call `ctk` (see the README for the install) and refer to `AGENTS.md`. `orchestrate` is not here: it
delegates to Claude Code's subagents.
