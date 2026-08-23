"""Fail when GitHub candidate files contain credentials or oversized non-LFS blobs."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GITHUB_BLOB_LIMIT = 100 * 1024 * 1024
TEXT_SCAN_LIMIT = 40 * 1024 * 1024

SECRET_PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OpenAI API key": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(rb"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}"),
    "Supabase secret key": re.compile(rb"\bsb_secret_[A-Za-z0-9_-]{12,}"),
    "Supabase publishable key": re.compile(rb"\bsb_publishable_[A-Za-z0-9_-]{12,}"),
    "AWS access key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
}
DATABASE_CREDENTIAL = re.compile(
    rb"postgres(?:ql)?(?:\+psycopg2)?://([^:\s/]+):([^@\s/]+)@([^/\s]+)",
    re.IGNORECASE,
)


def git_output(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def candidate_files() -> list[Path]:
    output = git_output("ls-files", "-co", "--exclude-standard", "-z")
    return [ROOT / item.decode("utf-8") for item in output.split(b"\0") if item]


def lfs_paths(paths: list[Path]) -> set[Path]:
    relative_paths = [path.relative_to(ROOT).as_posix() for path in paths]
    payload = b"\0".join(item.encode("utf-8") for item in relative_paths) + b"\0"
    result = subprocess.run(
        ["git", "check-attr", "-z", "--stdin", "filter"],
        cwd=ROOT,
        input=payload,
        check=True,
        capture_output=True,
    )
    fields = result.stdout.split(b"\0")
    covered: set[Path] = set()
    for index in range(0, len(fields) - 2, 3):
        if fields[index + 2] == b"lfs":
            covered.add(ROOT / fields[index].decode("utf-8"))
    return covered


def safe_database_example(match: re.Match[bytes]) -> bool:
    _, password, host = (part.decode("utf-8", errors="ignore") for part in match.groups())
    safe_passwords = {"p", "password", "postgres", "<password>", "${password}"}
    safe_hosts = {"localhost", "127.0.0.1", "postgres", "host"}
    return password.lower() in safe_passwords or host.lower().split(":", 1)[0] in safe_hosts


def main() -> int:
    files = candidate_files()
    lfs_files = lfs_paths(files)
    oversized: list[str] = []
    findings: list[str] = []

    for path in files:
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size > GITHUB_BLOB_LIMIT and path not in lfs_files:
            oversized.append(f"{path.relative_to(ROOT)} ({size / 1024 / 1024:.1f} MiB)")
        if path in lfs_files or size > TEXT_SCAN_LIMIT:
            continue
        body = path.read_bytes()
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(body):
                findings.append(f"{path.relative_to(ROOT)}: possible {label}")
        for match in DATABASE_CREDENTIAL.finditer(body):
            if not safe_database_example(match):
                findings.append(f"{path.relative_to(ROOT)}: possible database credential")
                break

    if oversized or findings:
        if oversized:
            print("Oversized files not covered by Git LFS:")
            print("\n".join(f"- {item}" for item in oversized))
        if findings:
            print("Possible credentials in Git candidate files:")
            print("\n".join(f"- {item}" for item in sorted(set(findings))))
        return 1

    ignored = [".env", "frontend/.env.local", ".scrapy/httpcache"]
    for ignored_path in ignored:
        subprocess.check_call(
            ["git", "check-ignore", "--quiet", "--", ignored_path], cwd=ROOT
        )
    lfs_count = sum(path in lfs_files for path in files if path.is_file())
    total_size = sum(path.stat().st_size for path in files if path.is_file())
    print(
        f"Repository readiness scan passed: {len(files)} candidate files, "
        f"{total_size / 1024 / 1024:.1f} MiB, {lfs_count} Git LFS files."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
