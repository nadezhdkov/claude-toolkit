#!/usr/bin/env bash
# Pass when the quoting and the --csv option work.
here=$(cd "$(dirname "$0")" && pwd)
mods=""; for c in TestQuoting TestCliFlag; do mods="$mods hidden_tests.$c"; done
if PYTHONPATH="$PWD:$here" python3 -m unittest $mods >/tmp/ctk-check.log 2>&1; then
  echo "the quoting and the --csv option work"
  exit 0
fi
tail -5 /tmp/ctk-check.log
echo "FAILED: the quoting and the --csv option work"
exit 1
