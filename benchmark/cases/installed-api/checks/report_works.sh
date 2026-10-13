#!/usr/bin/env bash
out=$(.venv/bin/python report.py Lisbon 2>&1) || { echo "report.py failed: ${out##*$'\n'}"; exit 1; }
[ "$out" = "Lisbon: 21.5 °C" ] || { echo "unexpected output: $out"; exit 1; }
echo "report.py prints the right line"
