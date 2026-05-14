#!/usr/bin/env python3
"""Warn (or fail with --strict) if any package in uv.lock was uploaded recently.

The goal is to flag potentially compromised packages that were yanked or replaced
shortly after release. By default we surface a warning so urgent CVE fixes are
not blocked; pass --strict to make it a hard failure (suitable for hardened
environments).
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

MIN_AGE_DAYS = 7
LOCK = Path(__file__).resolve().parent.parent / "uv.lock"


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any package is younger than the threshold.",
    )
    parser.add_argument(
        "--min-age-days",
        type=int,
        default=MIN_AGE_DAYS,
        help=f"Minimum acceptable package age in days (default: {MIN_AGE_DAYS}).",
    )
    args = parser.parse_args()

    data = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.min_age_days)
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

    total = len(data.get("package", []))
    if not violations:
        print(f"OK: all {total} packages are older than {args.min_age_days} days.")
        return 0

    level = "ERROR" if args.strict else "WARNING"
    print(
        f"{level}: {len(violations)} of {total} packages uploaded within the "
        f"last {args.min_age_days} days:",
        file=sys.stderr,
    )
    for name, version, ts in violations:
        print(f"  {name}=={version}  uploaded {ts}", file=sys.stderr)
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
