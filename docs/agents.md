# Subagents and orchestration (`ctk` plugin)

Three subagents for noisy or independent work, each with an **output contract**
that a hook enforces, and an `orchestrate` skill that says when and how to use them.

| Agent | Does | Tools | Model | Contract |
|---|---|---|---|---|
| [`ctk:test-runner`](../plugin/agents/test-runner.md) | runs tests, type checks, linters or builds through `ctk runq` and diagnoses failures | Bash, Read, Grep, Glob | haiku | ≤25 lines; failures with `path:line` or test id; `VERDICT: pass \| fail \| error` |
| [`ctk:reviewer`](../plugin/agents/reviewer.md) | reviews a diff for bugs, regressions, missing tests and risk, verifying each finding | Read, Grep, Glob, Bash, LSP | inherit | ≤40 lines; findings with `path:line`, scenario and evidence; `VERDICT: approve \| changes-requested \| blocked` |
| [`ctk:researcher`](../plugin/agents/researcher.md) | answers one question from code, installed dependencies (`ctk libdocs`) and docs | Read, Grep, Glob, Bash, LSP, WebFetch, WebSearch | sonnet | ≤30 lines; every claim with `path:line` or URL; `VERDICT: answered \| partial \| not-found` |

None of them can edit files or start other agents (`disallowedTools: Edit, Write,
NotebookEdit, Agent`): they report and the main conversation decides. Claude
delegates to them on its own when their description fits, or you ask for one by
name (`use the ctk:reviewer agent on this branch`, `@agent-ctk:reviewer`).

## Output contracts

Each agent file declares its contract in the frontmatter, which is the only
place it is written:

```yaml
ctk-contract: max-lines=40; verdicts=approve,changes-requested,blocked; evidence-for=changes-requested
```

The `agent-contract` hook (`SubagentStop`, matched to these three agents)
checks the final report:

- at most `max-lines` lines;
- the last line is `VERDICT: <verdict>` with an allowed verdict;
- for the verdicts in `evidence-for`, at least one `path:line`, test id
  (`file.py::test`) or URL.

A report that breaks it is sent back once with the list of problems ("rewrite
only the final report"); if the rewrite still breaks it, the report is
delivered and the user sees a warning. So the main conversation always gets a
short report that ends in a verdict it can act on.

## Orchestration

The [`orchestrate`](../plugin/skills/orchestrate/SKILL.md) skill
(`/ctk:orchestrate`) covers:

- **when to delegate** (noisy, independent, second opinion) and when not to
  (small or sequential work, work that needs the conversation's context, the
  user's decisions);
- **briefs** that stand alone: goal, context, constraints, return;
- **parallel fan-out** of independent agents in one turn (two to four);
- the **verify loop**: `test-runner` and `reviewer` in parallel after a change,
  fix what the evidence supports, rerun only what failed, stop after three
  rounds and report;
- **reading results** as evidence to check (open the cited lines before acting).

## Cost

Agent descriptions are listed in every session like skill descriptions; the
three add about 180 tokens, and the whole plugin about 580
(`claude plugin details ctk`). A subagent's own
work stays in its context; only its report (at most 25–40 lines) comes back.

## Done criteria (tested in `tests/test_agents.py`)

- Every agent is read-only and cannot spawn agents, has a short description
  and a contract whose verdicts its instructions document.
- Reports that follow the contract pass; a missing or invalid verdict, a
  report over the limit or a verdict without evidence is sent back once, then
  passed with a warning; other agents are ignored.
- The contract is found through the plugin root and, without it, through the
  checkout.
