#!/usr/bin/env bash
# The fix is real: the unchanged runner passes now.
sha256sum -c /tmp/run_tests.sha256 >/dev/null 2>&1 || { echo "run_tests.py was modified"; exit 1; }
python3 run_tests.py >/dev/null 2>&1 || { echo "the suite still fails"; exit 1; }
echo "suite passes, runner unchanged"
