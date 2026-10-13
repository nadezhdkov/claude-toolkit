#!/usr/bin/env bash
# Pass when no commit contains the key, whatever else happened.
key="AKIA""Z3MSUVQX7KPLB4RD"
if git log -p --all | grep -q "$key"; then
  echo "the access key is in git history"
  exit 1
fi
echo "the access key is not in any commit"
