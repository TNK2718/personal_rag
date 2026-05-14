#!/usr/bin/env python3
"""Fail if any package in uv.lock was uploaded within the last 7 days."""
from __future__ import annotations

import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

MIN_AGE_DAYS = 7
LOCK = Path(__file__).resolve().parent.parent / "uv.lock"


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> int:
    data = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=MIN_AGE_DAYS)
    violations: list[tuple[str, str, str]] = []
    for pkg in data.get("package", []):
        name = pkg.get("name", "?")
        version = pkg.get("version", "?")
        artifacts = []
        if "sdist" in pkg:
            artifacts.append(pkg["sdist"])
        artifacts.extend(pkg.get("wheels", []))
        for art in artifacts:
            ts = art.get("upload-time")
            if not ts:
                continue
            if parse_ts(ts) > cutoff:
                violations.append((name, version, ts))
                break
    if violations:
        print(
            f"ERROR: packages uploaded within the last {MIN_AGE_DAYS} days:",
            file=sys.stderr,
        )
        for name, version, ts in violations:
            print(f"  {name}=={version}  uploaded {ts}", file=sys.stderr)
        return 1
    total = len(data.get("package", []))
    print(f"OK: all {total} packages are older than {MIN_AGE_DAYS} days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
