#!/usr/bin/env bash
# Pass when the quoting and the --csv option work.
here=$(cd "$(dirname "$0")" && pwd)
if PYTHONPATH="$PWD:$here" python3 -m unittest hidden_tests.TestQuoting hidden_tests.TestCliFlag >/tmp/ctk-check.log 2>&1; then
  echo "the quoting and the --csv option work"
  exit 0
fi
tail -5 /tmp/ctk-check.log
echo "FAILED: the quoting and the --csv option work"
exit 1
