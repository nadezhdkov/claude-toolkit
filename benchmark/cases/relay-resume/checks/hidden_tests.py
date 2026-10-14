"""What the finished feature must do. Run by the checks, from /work; Claude is never told about it."""

import contextlib
import io
import json
import os
import tempfile
import unittest

import cli
from invoices import Invoice, Line, export_csv


def invoice(customer, cents=1999):
    return Invoice("A-1", customer, [Line("thing", cents)])


class TestQuoting(unittest.TestCase):
    def test_comma(self):
        self.assertIn('A-1,"Acme, Inc.",19.99\n', export_csv([invoice("Acme, Inc.")]))

    def test_quote_is_doubled(self):
        self.assertIn('A-1,"Say ""hi""",19.99\n', export_csv([invoice('Say "hi"')]))

    def test_line_break(self):
        self.assertIn('A-1,"two\nlines",19.99\n', export_csv([invoice("two\nlines")]))

    def test_plain_fields_are_left_alone(self):
        self.assertEqual(export_csv([invoice("Acme")]), "number,customer,total\nA-1,Acme,19.99\n")


class TestDecisions(unittest.TestCase):
    def test_bare_newline_only(self):
        self.assertNotIn("\r", export_csv([invoice("Acme"), invoice("Acme, Inc.")]))

    def test_totals_come_from_cents(self):
        self.assertIn("A-1,Acme,0.05\n", export_csv([invoice("Acme", 5)]))
        self.assertIn("A-1,Acme,0.30\n", export_csv([Invoice("A-1", "Acme", [Line("a", 10), Line("b", 20)])]))

    def test_the_file_the_option_writes_keeps_them_too(self):
        """Also fails when the feature was never finished: there is no file to look at."""
        data = [{"number": "A-1", "customer": "Acme, Inc.", "lines": [{"description": "x", "cents": 5}]}]
        with tempfile.TemporaryDirectory() as folder:
            source, target = os.path.join(folder, "in.json"), os.path.join(folder, "out.csv")
            with open(source, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main([source, "--csv", target])
            with open(target, "rb") as handle:
                written = handle.read()
        self.assertNotIn(b"\r", written)
        self.assertIn(b",0.05\n", written)

    def test_no_float_in_the_source(self):
        for name in ("invoices.py", "cli.py"):
            with open(name, encoding="utf-8") as handle:
                self.assertNotIn("float(", handle.read(), name)


class TestCliFlag(unittest.TestCase):
    def test_csv_option_writes_the_file(self):
        data = [{"number": "A-1", "customer": "Acme, Inc.", "lines": [{"description": "x", "cents": 1999}]}]
        with tempfile.TemporaryDirectory() as folder:
            source, target = os.path.join(folder, "in.json"), os.path.join(folder, "out.csv")
            with open(source, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main([source, "--csv", target])
            with open(target, "rb") as handle:
                written = handle.read()
        self.assertEqual(code, 0)
        self.assertEqual(written, b'number,customer,total\nA-1,"Acme, Inc.",19.99\n')


if __name__ == "__main__":
    unittest.main()
