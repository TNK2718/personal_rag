#!/usr/bin/env python3
"""Keep ``[tool.uv] exclude-newer`` rolling at ``today - MIN_AGE_DAYS``.

Used as a pre-commit hook so every `uv lock` / `uv add` invocation
respects the minimum package age policy at resolution time. Idempotent:
exits 0 with no changes when the value is already at or ahead of the
target date.
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MIN_AGE_DAYS = 7
PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def parse_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def update(content: str, target: str, target_date: date) -> tuple[str, bool]:
    """Return (new_content, changed). Only moves the cutoff date forward,
    so a manual bump for an urgent CVE override is preserved until time
    naturally catches up."""
    pattern = re.compile(
        r'(?ms)^\[tool\.uv\]\s*\n(?P<body>(?:(?!^\[).*\n?)*)'
    )
    match = pattern.search(content)
    if match:
        body = match.group("body")
        key_pattern = re.compile(r'(?m)^exclude-newer\s*=\s*"([^"]+)"')
        key_match = key_pattern.search(body)
        if key_match:
            current_date = parse_date(key_match.group(1))
            if current_date and current_date >= target_date:
                return content, False
            new_body = key_pattern.sub(f'exclude-newer = "{target}"', body, count=1)
        else:
            new_body = f'exclude-newer = "{target}"\n' + body
        return content[: match.start("body")] + new_body + content[match.end("body") :], True

    appended = content.rstrip() + f'\n\n[tool.uv]\nexclude-newer = "{target}"\n'
    return appended, True


def main() -> int:
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=MIN_AGE_DAYS)).date()
    target = f"{cutoff_date.isoformat()}T00:00:00Z"
    original = PYPROJECT.read_text(encoding="utf-8")
    new_content, changed = update(original, target, cutoff_date)
    if not changed:
        return 0
    PYPROJECT.write_text(new_content, encoding="utf-8")
    print(
        f"Updated tool.uv.exclude-newer to {target} in {PYPROJECT.name}.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
