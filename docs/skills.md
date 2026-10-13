# Skills (`ctk` plugin)

Process skills for work that needs judgement, shipped in the `ctk` plugin
(`plugin/skills/`). Claude loads one automatically when its description fits
the task, or you call it as `/ctk:<name>`. Each skill uses the `ctk` commands
for the deterministic parts (`doctor`, `runq`, `lsp`, `shoot`, `audiocheck`).

| Skill | Use it to | Uses |
|---|---|---|
| [`debug`](../plugin/skills/debug/SKILL.md) | find and prove a root cause before fixing: reproduce, rule out the environment, bisect, regression test | `ctk runq`, `ctk doctor`, `ctk lsp`, `git bisect` |
| [`ship`](../plugin/skills/ship/SKILL.md) | finish a change: branch, sync, checks, diff review, changelog, Conventional Commit, PR, CI | `ctk runq`, `gh`, `visual-qa`, `security-pass`, `handoff` |
| [`handoff`](../plugin/skills/handoff/SKILL.md) | write or resume a per-branch progress file across sessions | `.claude/handoff/<branch>.md` (kept local through `.git/info/exclude`) |
| [`onboard-repo`](../plugin/skills/onboard-repo/SKILL.md) | get oriented in an unfamiliar repository and report a short brief | `ctk doctor`, `ctk lsp`, `ctk runq` |
| [`visual-qa`](../plugin/skills/visual-qa/SKILL.md) | check UI changes by looking at deterministic screenshots against a defect checklist and baselines | `ctk shoot` |
| [`security-pass`](../plugin/skills/security-pass/SKILL.md) | review a change for injection, path traversal, auth gaps, secrets and supply-chain risk, with evidence | gitleaks, zizmor, ecosystem audits when installed |

## Project processes come first

`ship`, `handoff` and `onboard-repo` look for the project's own rules first
(`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, a project skill with the same
purpose) and fill only the gaps. A project skill such as `.claude/skills/ship`
keeps its own name (`/ship`); the plugin's is `/ctk:ship`.

## Cost

The plugin's skill descriptions add about 650 tokens to every session
(`claude plugin details ctk`); a skill's body is read only when it is used
(about 750–1,000 tokens each). Per the design rules, a skill that `ctk
sessions --since 30` shows unused is a candidate for removal.

## Done criteria (tested in `tests/test_skills.py`)

- Every skill has valid frontmatter whose `name` matches its directory, a
  description of at most 400 characters and a body under 200 lines.
- Every `ctk` command and `ctk shoot` kind a skill mentions exists, and every
  skill it refers to exists.
- `claude plugin validate ./plugin` passes.
