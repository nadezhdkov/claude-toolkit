#!/usr/bin/env bash
# Pass when the earlier work is still there and the project's own tests pass.
log=$(git log --format=%s)
for subject in "feat: invoices with money in integer cents" "feat: export invoices as CSV (header and rows)"; do
  if ! grep -qxF "$subject" <<<"$log"; then
    echo "the earlier commit was rewritten or lost: $subject"
    exit 1
  fi
done
if ! python3 -m unittest discover -s tests -t . >/tmp/ctk-check.log 2>&1; then
  tail -5 /tmp/ctk-check.log
  echo "the project's own tests fail"
  exit 1
fi
echo "the earlier commits are intact and the project's tests pass"
