#!/usr/bin/env bash
# A calculator with two bugs and a pytest-style runner that prints every test.
set -euo pipefail
cat > calc.py <<'EOF'
"""Small money helpers."""


def add(a, b):
    return a + b


def divide(a, b):
    """Split an amount into b equal parts."""
    return a // b


def parse_amount(text):
    """Parse '12.50', '-3', ' 7 ' into a float."""
    return float(text.strip().lstrip("-"))
EOF
cat > run_tests.py <<'EOF'
"""Runs every calc test and prints a pytest-style report."""
import sys
import time
import traceback

import calc

CASES = []
for i in range(1, 401):
    CASES.append(("test_add", (i, i * 2), 3 * i))
for i in range(1, 301):
    CASES.append(("test_divide", (i * 7, 4), i * 7 / 4))
for i in range(1, 201):
    sign = -1 if i % 2 else 1
    CASES.append(("test_parse_amount", (f" {sign * i}.25 ",), sign * (i + 0.25)))

FUNCS = {"test_add": calc.add, "test_divide": calc.divide, "test_parse_amount": calc.parse_amount}


def main():
    start = time.time()
    print("============================= test session starts ==============================")
    print(f"collected {len(CASES)} items")
    failures = []
    for index, (name, args, expected) in enumerate(CASES):
        test_id = f"tests/test_calc.py::{name}[{index}]"
        try:
            got = FUNCS[name](*args)
            assert abs(got - expected) < 1e-9, f"assert {got!r} == {expected!r}"
            print(f"{test_id} PASSED")
        except Exception as error:  # noqa: BLE001
            print(f"{test_id} FAILED")
            failures.append((test_id, name, args, error, traceback.format_exc()))
    if failures:
        print("=================================== FAILURES ===================================")
        for test_id, name, args, error, trace in failures:
            print(f"____________________________ {test_id} ____________________________")
            print(f"    args = {args!r}")
            for line in trace.strip().splitlines():
                print(f"E   {line}")
        print("=========================== short test summary info ============================")
        for test_id, _name, _args, error, _trace in failures:
            print(f"FAILED {test_id} - AssertionError: {error}")
    passed = len(CASES) - len(failures)
    summary = f"{len(failures)} failed, {passed} passed" if failures else f"{passed} passed"
    print(f"========================= {summary} in {time.time() - start:.2f}s =========================")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
EOF
sha256sum run_tests.py > /tmp/run_tests.sha256
