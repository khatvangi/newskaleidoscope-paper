#!/usr/bin/env python3
"""
migrate.py — run Alembic migrations cleanly.

usage:
    python3 migrate.py              # upgrade to latest
    python3 migrate.py downgrade    # downgrade one revision
    python3 migrate.py status       # show current revision
"""

import sys
import subprocess


def run_alembic(cmd):
    """run an alembic command."""
    result = subprocess.run(
        ["alembic"] + cmd,
        capture_output=True, text=True,
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        # alembic writes INFO to stderr
        for line in result.stderr.strip().split("\n"):
            if "ERROR" in line or "FAILED" in line:
                print(f"ERROR: {line}")
            else:
                print(line)
    return result.returncode


def main():
    if len(sys.argv) < 2 or sys.argv[1] == "upgrade":
        print("upgrading to latest migration...")
        return run_alembic(["upgrade", "head"])
    elif sys.argv[1] == "downgrade":
        print("downgrading one revision...")
        return run_alembic(["downgrade", "-1"])
    elif sys.argv[1] == "status":
        return run_alembic(["current"])
    else:
        print(f"unknown command: {sys.argv[1]}")
        print("usage: python3 migrate.py [upgrade|downgrade|status]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
