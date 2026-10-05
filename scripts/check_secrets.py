"""Check tracked/source candidates without reading private runtime folders."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DENIED_PARTS = {
    "data",
    ".venv",
    ".cache",
    "node_modules",
    ".codex",
    ".ssh",
    "test-results",
    "playwright-report",
}
DENIED_NAMES = {"auth.json", "master.key", "credentials.json", "config.json"}
PATTERNS = [
    re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
]


def main():
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={ROOT.as_posix()}",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    names = set(filter(None, result.stdout.decode("utf-8").split("\0")))
    problems = []
    for name in sorted(names):
        path = Path(name)
        if (
            set(path.parts) & DENIED_PARTS
            or path.name in DENIED_NAMES
            or (path.name.startswith(".env") and path.name != ".env.example")
            or path.suffix in {".db", ".sqlite", ".sqlite3", ".key", ".pem"}
        ):
            problems.append((name, "private runtime file in source candidates"))
            continue
        absolute = ROOT / name
        if not absolute.is_file() or absolute.suffix.lower() in {".png", ".jpg", ".woff2"}:
            continue
        content = absolute.read_text(encoding="utf-8", errors="replace")
        if any(pattern.search(content) for pattern in PATTERNS):
            # Report paths only. Never print matching credential material.
            problems.append((name, "possible credential"))
    for name, problem in problems:
        print(f"FAIL {name}: {problem}")
    if problems:
        return 1
    print(f"Checked {len(names)} source candidates: no credential patterns or private runtime files found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
