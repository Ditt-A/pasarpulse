#!/usr/bin/env python3
"""Fail closed on high-confidence secrets and private infrastructure traces.

The scanner intentionally prints only the rule name and file/commit location;
it never echoes a matched credential value. Use ``--history`` before making the
repository public to scan every reachable commit patch as well as the current
working tree.
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
from pathlib import Path


HIGH_CONFIDENCE_RULES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private-key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github-token", re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("google-api-key", re.compile(rb"AIza[0-9A-Za-z_-]{30,}")),
    ("openai-style-key", re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("aws-access-key", re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}")),
    ("slack-token", re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,}")),
    ("jupyter-auth-token", re.compile(rb"Authorization\s*:\s*token\s+[0-9A-Fa-f]{16,}", re.I)),
    ("credential-in-url", re.compile(rb"https?://[^/\s:@]+:[^@\s/]+@", re.I)),
    ("private-jupyter-host", re.compile(rb"node\d+-ai-hub\.ub\.ac\.id/user/", re.I)),
    ("private-a100-workspace", re.compile(rb"/home/[^/\s]+/adit/datathon-semi/", re.I)),
)

LITERAL_ASSIGNMENT = re.compile(
    rb"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|token)\b"
    rb"\s*[:=]\s*['\"]([^'\"\r\n]{16,})['\"]"
)

SAFE_LITERAL_MARKERS = (
    b"placeholder",
    b"example",
    b"dummy",
    b"test",
    b"change_me",
    b"changeme",
    b"your_",
    b"<token>",
    b"<key>",
    b"[redacted]",
    b"redacted",
    b"localhost",
)

SAFE_URL_TEMPLATE_MARKERS = (
    b"${",
    b"$GITHUB_",
    b"GITHUB_TOKEN",
    b"{{",
    b"%s",
    b"<token>",
    b"[redacted]",
)

FORBIDDEN_EXACT = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".cdsapirc",
    ".netrc",
    "setup_credentials.py",
    "credentials.json",
    "service-account.json",
}
FORBIDDEN_GLOBS = ("*.pem", "*.key", "*.p12", "*.pfx", "service-account*.json")
ALLOW_EXACT = {".env.example"}


def _tracked_files() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files", "-z"])
    return [Path(item.decode("utf-8", "surrogateescape")) for item in raw.split(b"\0") if item]


def _forbidden_filename(path: Path) -> bool:
    posix = path.as_posix()
    name = path.name
    if posix in ALLOW_EXACT or name in ALLOW_EXACT:
        return False
    if posix in FORBIDDEN_EXACT or name in FORBIDDEN_EXACT:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in FORBIDDEN_GLOBS)


def _scan_bytes(payload: bytes) -> list[str]:
    hits: list[str] = []
    for name, pattern in HIGH_CONFIDENCE_RULES:
        match = pattern.search(payload)
        if not match:
            continue
        if name == "credential-in-url" and any(marker in match.group(0) for marker in SAFE_URL_TEMPLATE_MARKERS):
            continue
        hits.append(name)
    for match in LITERAL_ASSIGNMENT.finditer(payload):
        value = match.group(2).strip().lower()
        if any(marker in value for marker in SAFE_LITERAL_MARKERS):
            continue
        if b"getenv" in value or b"process.env" in value or b"settings[" in value or b"os.environ" in value:
            continue
        hits.append("literal-secret-assignment")
        break
    return hits


def scan_current() -> list[str]:
    findings: list[str] = []
    for path in _tracked_files():
        if _forbidden_filename(path):
            findings.append(f"forbidden-file: {path.as_posix()}")
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        for rule in _scan_bytes(payload):
            findings.append(f"{rule}: {path.as_posix()}")
    return findings


def scan_history() -> list[str]:
    findings: list[str] = []
    process = subprocess.Popen(
        ["git", "log", "--all", "-p", "--no-color", "--no-ext-diff", "--no-renames"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    current_commit = "unknown"
    current_path = "unknown"
    seen: set[tuple[str, str, str]] = set()
    for raw_line in process.stdout:
        if raw_line.startswith(b"commit "):
            current_commit = raw_line.split(maxsplit=1)[1].decode("ascii", "replace").strip()[:12]
            continue
        if raw_line.startswith(b"+++ b/"):
            current_path = raw_line[6:].decode("utf-8", "replace").strip()
            continue
        if not raw_line.startswith((b"+", b"-")) or raw_line.startswith((b"+++", b"---")):
            continue
        payload = raw_line[1:]
        for rule in _scan_bytes(payload):
            key = (rule, current_commit, current_path)
            if key not in seen:
                seen.add(key)
                findings.append(f"{rule}: {current_commit}:{current_path}")
    stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
    return_code = process.wait()
    if return_code:
        raise RuntimeError(f"git log scan failed with exit {return_code}: {stderr.strip()}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true", help="also scan reachable Git history patches")
    args = parser.parse_args()

    findings = scan_current()
    if args.history:
        findings.extend(scan_history())

    if findings:
        print(f"Public-release scan failed with {len(findings)} finding(s).")
        for finding in sorted(set(findings)):
            print(f"- {finding}")
        print("Matched credential values are intentionally not printed.")
        return 1

    scope = "tracked files and reachable history" if args.history else "tracked files"
    print(f"Public-release scan passed: no high-confidence secret/private-host findings in {scope}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
