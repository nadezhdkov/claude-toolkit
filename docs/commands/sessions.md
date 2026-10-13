# `ctk sessions`

Measures how Claude Code actually works, from its own transcripts, so every
toolkit change can be judged by data instead of impressions.

```bash
ctk sessions                     # all transcripts
ctk sessions --since 30          # sessions active in the last 30 days
ctk sessions --project myapp     # working directory contains "myapp"
ctk sessions --no-subagents      # ignore subagent transcripts
ctk sessions --csv -             # weekly rows as CSV on stdout
ctk sessions --csv weekly.csv    # ... or into a file
ctk sessions --json              # the full summary as JSON
```

## Metrics

| Metric | Meaning | Expected to fall after |
|---|---|---|
| tool calls / errors | all tool calls and those whose result was an error | `doctor`, `libdocs` |
| explore calls before 1st edit | Read, Grep, Glob, LSP and read-only shell commands (`cat`, `grep`, `rg`, `ls`…) before the first Edit/Write, median per session | `lsp`, `onboard-repo` |
| Read calls before 1st edit | the Read subset of the above | `lsp` |
| Bash output | average and maximum characters returned by shell commands (≈ ÷4 tokens) | `runq` |
| all tool results | total characters returned by tools | `runq` |
| "file changed on disk" notices | notices Claude receives when a file changes after it was edited, per session | must not rise after formatting hooks |
| tokens read (context) | everything the model read, from the transcripts' usage records: fresh input, cache writes and cache reads, with the share served from cache | `runq`, `map`, subagents |
| tokens written | output tokens and the number of model calls | — |
| context per session | average tokens read per session, and the median and largest **peak window** (the most one call read: how full the context got) | `runq`, `map`, `handoff` |
| compactions | conversation compactions, and how many sessions had one | `map`, subagents |
| results re-read later | each tool result's size × the model calls that read it again before the end or the next compaction, by tool: what an output really cost | `runq`, `libdocs`, `map` |
| repeated reads of a file | `Read` calls on a file already read in the same session (counted through a hash; names are never kept) | `map`, `handoff` |
| skills, subagents, MCP servers, ctk commands | usage counts | used for the monthly review |

### Why "re-read later" matters

Every model call reads the whole context again (mostly from the prompt
cache). A 10,000-token command output early in a 300-call session is read
about 3 million times over, so the total of tool outputs understates their
cost by orders of magnitude; "results re-read later" counts it the way the
model pays for it.

## Privacy

Only counts, tool names, skill/subagent names, MCP server names and `ctk`
subcommand names are extracted. Message text, file contents, prompts and
command output are never copied into the report.

## Data source

`~/.claude/projects/<project>/<session>.jsonl` and
`~/.claude/projects/<project>/<session>/subagents/*.jsonl`. Lines that cannot
carry a metric are skipped before JSON decoding, so hundreds of megabytes are
processed in a few seconds.

## Monthly review

Run `ctk sessions --since 30`: any toolkit piece with zero uses in 30 days is a
candidate for removal (see [design principle 1](../design.md)).
