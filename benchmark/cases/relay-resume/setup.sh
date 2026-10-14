#!/usr/bin/env bash
# A small invoicing project in the middle of a feature (export invoices as CSV). The previous session
# committed the first half, wrote a handoff file with the decisions that are not in the code, and left
# one uncommitted edit. A fresh session starts here.
set -euo pipefail
git init -q
git checkout -q -b feat/csv-export
mkdir -p tests .claude/handoff
touch tests/__init__.py  # so a plain `python3 -m unittest` finds the tests
printf '.claude/handoff/\n' >> .git/info/exclude

cat > invoices.py <<'EOF'
"""Invoices. Money is kept in integer cents."""

from dataclasses import dataclass


@dataclass
class Line:
    description: str
    cents: int
    quantity: int = 1


@dataclass
class Invoice:
    number: str
    customer: str
    lines: list[Line]

    def total_cents(self) -> int:
        return sum(line.cents * line.quantity for line in self.lines)


def format_cents(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"
EOF

cat > cli.py <<'EOF'
"""Print invoices from a JSON file."""

import argparse
import json

from invoices import Invoice, Line, format_cents


def load(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return [Invoice(item["number"], item["customer"], [Line(**line) for line in item["lines"]]) for item in data]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file")
    parser.add_argument("--total", action="store_true", help="print only the grand total")
    args = parser.parse_args(argv)
    invoices = load(args.file)
    if args.total:
        print(format_cents(sum(invoice.total_cents() for invoice in invoices)))
        return 0
    for invoice in invoices:
        print(f"{invoice.number}  {invoice.customer}  {format_cents(invoice.total_cents())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
EOF

cat > tests/test_invoices.py <<'EOF'
import unittest

from invoices import Invoice, Line, format_cents


class TestInvoices(unittest.TestCase):
    def test_total_is_in_cents(self):
        invoice = Invoice("A-1", "Acme", [Line("pens", 250, 4), Line("paper", 1999)])
        self.assertEqual(invoice.total_cents(), 2999)

    def test_format_cents(self):
        self.assertEqual(format_cents(1999), "19.99")
        self.assertEqual(format_cents(5), "0.05")


if __name__ == "__main__":
    unittest.main()
EOF

cat > tests/test_cli.py <<'EOF'
import contextlib
import io
import json
import os
import tempfile
import unittest

import cli


class TestCli(unittest.TestCase):
    def run_cli(self, *extra):
        data = [{"number": "A-1", "customer": "Acme", "lines": [{"description": "pens", "cents": 250, "quantity": 4}]}]
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "in.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main([path, *extra])
        return code, out.getvalue()

    def test_total_flag(self):
        self.assertEqual(self.run_cli("--total"), (0, "10.00\n"))


if __name__ == "__main__":
    unittest.main()
EOF
git add -A
git -c user.name=dev -c user.email=dev@example.com commit -q -m "feat: invoices with money in integer cents"

python3 - <<'EOF'
import re
text = open("invoices.py", encoding="utf-8").read()
text += '''

def export_csv(invoices):
    """One row per invoice."""
    rows = ["number,customer,total"]
    for invoice in invoices:
        rows.append(f"{invoice.number},{invoice.customer},{format_cents(invoice.total_cents())}")
    return "\\n".join(rows) + "\\n"
'''
open("invoices.py", "w", encoding="utf-8").write(text)
EOF
cat > tests/test_export.py <<'EOF'
import unittest

from invoices import Invoice, Line, export_csv


class TestExport(unittest.TestCase):
    def test_header(self):
        self.assertTrue(export_csv([]).startswith("number,customer,total\n"))

    def test_rows(self):
        invoices = [Invoice("A-1", "Acme", [Line("pens", 250, 4)]), Invoice("B-2", "Bolt", [Line("nut", 5)])]
        self.assertEqual(export_csv(invoices), "number,customer,total\nA-1,Acme,10.00\nB-2,Bolt,0.05\n")


if __name__ == "__main__":
    unittest.main()
EOF
git add -A
git -c user.name=dev -c user.email=dev@example.com commit -q -m "feat: export invoices as CSV (header and rows)"

# The previous session's last, uncommitted edit: the option is declared but not wired to anything.
python3 - <<'EOF'
text = open("cli.py", encoding="utf-8").read()
needle = '    parser.add_argument("--total"'
text = text.replace(needle, '    parser.add_argument("--csv", metavar="OUT", help="write the invoices as CSV")\n' + needle, 1)
open("cli.py", "w", encoding="utf-8").write(text)
EOF

sha=$(git rev-parse --short HEAD)
cat > .claude/handoff/feat-csv-export.md <<EOF
# feat/csv-export — export invoices as CSV for the accountant

Updated: $(date +%Y-%m-%d) · Commit: ${sha} · PR: none

## Status
\`export_csv()\` writes the header and one row per invoice, with each total formatted from integer cents.
Fields are not quoted yet, so a customer name with a comma breaks the file. The \`--csv OUT\` option is
declared in cli.py (uncommitted) but not wired to anything.

## Done
- \`export_csv\` in invoices.py, with tests/test_export.py (header and rows).

## Next
1. Quote fields that contain a comma, a double quote or a line break in \`export_csv\` (wrap the field in
   double quotes and double any quote inside it), with tests in tests/test_export.py.
2. Wire \`--csv OUT\` in cli.py \`main()\`: write \`export_csv(invoices)\` to OUT.

## Decisions
- Money stays in integer cents all the way and is printed with two decimals through \`format_cents\`.
  Never use float: 0.1 + 0.2 once made a total 30 cents off.
- Lines end with a bare "\\n", never "\\r\\n": the accountant's importer rejects CRLF. (So the csv module's
  default writer is out.)
- No new dependencies.

## Verify
- \`python3 -m unittest\` passed at ${sha}.
EOF
