#!/usr/bin/env bash
# Gate: run twice more after the first pass, never once.
set -u
fail() { echo "GATE FAILED: $1"; exit 1; }

echo "== check 1/4: version consistency (pyproject vs module)"
py=$(grep -m1 -E '^version[[:space:]]*=' pyproject.toml | sed -E 's/.*"(.*)".*/\1/')
mod=$(grep -m1 -oE '__version__ = "[^"]+"' src/paymock/__init__.py | sed -E 's/.*"(.*)"/\1/')
echo "   pyproject=$py module=$mod"
[ "$py" = "$mod" ] || fail "version drift: $py vs $mod"

echo "== check 2/4: test suite"
python3 -m pytest -q || fail "tests"

echo "== check 3/4: CLI reports its version (never assume it matches the package)"
out=$(timeout 30 paymock --version 2>&1) || fail "paymock --version exited non-zero or hung"
echo "   $out"
[ "$out" = "paymock $py" ] || fail "--version says '$out', package is $py"

echo "== check 4/4: CLI help exits 0 without starting the server"
timeout 30 paymock --help >/dev/null 2>&1 || fail "paymock --help exited non-zero or hung"

echo "ALL CHECKS PASSED"
