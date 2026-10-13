---
description: A test suite with hundreds of failures from two bugs and thousands of output lines. Measures whether ctk keeps the context small without losing the fix.
plugins: ["../../../plugin"]
runs: 3
max_turns: 25
timeout_seconds: 600
allowed_tools: [Bash, Read, Edit, Write, Grep, Glob, Agent, Skill]
tags: [tokens, tests]
---

The test suite in this directory fails. Run it with `python3 run_tests.py`, find the distinct bugs, and fix them in calc.py (do not change run_tests.py). Run the suite again until it passes, then write the final summary line it prints to RESULT.txt.
