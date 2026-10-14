#!/usr/bin/env bash
# Pass when the decisions in the handoff were kept.
here=$(cd "$(dirname "$0")" && pwd)
mods=""; for c in TestDecisions; do mods="$mods hidden_tests.$c"; done
if PYTHONPATH="$PWD:$here" python3 -m unittest $mods >/tmp/ctk-check.log 2>&1; then
  echo "the decisions in the handoff were kept"
  exit 0
fi
tail -5 /tmp/ctk-check.log
echo "FAILED: the decisions in the handoff were kept"
exit 1
