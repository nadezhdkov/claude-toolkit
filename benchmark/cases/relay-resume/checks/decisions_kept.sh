#!/usr/bin/env bash
# Pass when the decisions in the handoff were kept.
here=$(cd "$(dirname "$0")" && pwd)
if PYTHONPATH="$PWD:$here" python3 -m unittest hidden_tests.TestDecisions >/tmp/ctk-check.log 2>&1; then
  echo "the decisions in the handoff were kept"
  exit 0
fi
tail -5 /tmp/ctk-check.log
echo "FAILED: the decisions in the handoff were kept"
exit 1
