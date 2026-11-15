"""Run the repository's synthetic regression suites with one command."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Run Finance Flow regression tests")
    parser.add_argument("--python-only", action="store_true", help="Skip JavaScript suites when Node.js is unavailable")
    options = parser.parse_args()
    node = None if options.python_only else shutil.which("node")
    if not options.python_only and not node:
        print("Install Node.js for the frontend tests, or run: python run_tests.py --python-only", flush=True)
        return 1
    commands = [
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "-m", "unittest", "discover", "-s", "rpa/tests", "-v"],
    ]
    if node:
        commands.append([node, "tests/assistant-navigation.cjs"])
        scripts = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("*.cjs")
                         if p.name != "assistant-navigation.cjs")
        commands.append([node, "--test", *scripts])
    for command in commands:
        print("\nRunning: " + subprocess.list2cmdline(command), flush=True)
        completed = subprocess.run(command, cwd=ROOT)
        if completed.returncode:
            print("Test run stopped after a failure.", flush=True)
            return completed.returncode
    print("\nAll selected test suites passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
