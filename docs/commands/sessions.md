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
ctk sessions --compare 2026-10-06..2026-10-13 2026-10-20..2026-10-27   # baseline vs current: pass or fail
ctk sessions --compare 14d..7d 7d..0d                                  # ... or relative to now
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
| window growth per call | median tokens a session's window grows per model call | `runq`, `runq-nudge` |
| relay point | the window size at which handing over to a fresh session would have cost least, what it saves and how many sessions would have relayed ([below](#relay-point)) | sets `[hooks.relay] threshold` |
| results re-read later | each tool result's size × the model calls that read it again before the end or the next compaction, by tool: what an output really cost | `runq`, `libdocs`, `map` |
| repeated reads of a file | `Read` calls on a file already read in the same session (counted through a hash; names are never kept) | `map`, `handoff` |
| skills, subagents, MCP servers, ctk commands | usage counts | used for the monthly review |

### Why "re-read later" matters

Every model call reads the whole context again (mostly from the prompt
cache). A 10,000-token command output early in a 300-call session is read
about 3 million times over, so the total of tool outputs understates their
cost by orders of magnitude; "results re-read later" counts it the way the
model pays for it.

## Relay point

Each session is replayed as if it had relayed (`ctk relay`) whenever its
window reached a threshold: from then on its window is what a fresh session
reads once it has resumed (the median window at the first edit, plus about
4,000 tokens of handoff), and each relay costs two extra calls at the old size
plus writing the new prefix to the cache (a cache write costs 12.5 cache
reads). Thresholds from 100k to 900k tokens are tried, skipping any below
twice the fresh window. Among those that save at least 90% of the best saving,
the highest wins: every relay costs some of the thread, which the model
cannot price. Under a 5% saving there is no relay point.

## Comparing two periods

`--compare BASELINE CURRENT` gives the Phase 8 verdict instead of two reports to read side by side.
Each period is `START..END`: two dates (both days included, UTC) or `Nd` for N days ago.
A session belongs to the period it ended in.

```text
ctk sessions · 2026-10-06..2026-10-13 → 2026-10-20..2026-10-27
  metric                                      baseline    current  change
  median peak window (tokens)*                 505,000    240,000  -52% ✓
  Bash re-read per session (tokens, median)  5,557,510  2,100,000  -62% ✓
  context read per session (tokens)        101,826,404 51,000,000  -50%
  compactions per session                         0.12       0.10  -17%
  sessions: 16 → 25 (* part of the Phase 8 criterion: both must fall by 50%)
PASS: both fell by at least half
```

The two starred metrics are the criterion: **both** must fall by at least half (exactly half
counts). The others only inform. With fewer than 5 sessions in a period, or no data for a
metric, the verdict is `INSUFFICIENT DATA`: a median of four sessions says nothing. The
benchmark scores are not read here; run `benchmark/run.py` and compare them separately.

Exit code `0` for a pass, `1` for a fail or insufficient data, `2` for a period that cannot be
read. `--json` prints the comparison with every metric.

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
