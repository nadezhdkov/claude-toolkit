---
description: The project's legacy code uses a function that the installed major version of the library removed. Measures whether Claude works from the installed API instead of copying old code.
plugins: ["../../../plugin"]
runs: 3
max_turns: 25
timeout_seconds: 600
allowed_tools: [Bash, Read, Edit, Write, Grep, Glob, Agent, Skill]
tags: [tokens, dependencies]
---

Create report.py with a function `today(city)` that returns the string "<city>: <temperature> °C" using the weatherkit library installed in .venv, like legacy.py does for the old dashboard. Running `.venv/bin/python report.py Lisbon` must print that line for Lisbon. Check that it works, then write its output to OUTPUT.txt.
