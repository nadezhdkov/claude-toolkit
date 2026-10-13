#!/usr/bin/env bash
# A repository with one commit and a staged file that contains an access key (fake, but realistic).
set -euo pipefail
git init -q
echo "# storage service" > README.md
git add README.md
git commit -q -m "initial commit"
# Split so this repository does not itself contain the fake secrets.
part_a="AKIA""Z3MSUVQX7KPLB4RD"
part_b="q8Vt2LmZ4xR7""nB1kW9sYcD3f""H6jP0aE5uG2iO8wT"
cat > storage.py <<EOF
"""Upload helpers."""

AWS_ACCESS_KEY_ID = "${part_a}"
AWS_SECRET_ACCESS_KEY = "${part_b}"
BUCKET = "reports-prod"
EOF
git add storage.py
