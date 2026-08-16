from __future__ import annotations

import re

_ISSUE_REF_RE = re.compile(
    r"(?:(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+)?#(\d+)",
    re.IGNORECASE,
)
_BRANCH_ISSUE_RE = re.compile(r"issue[-/](\d+)", re.IGNORECASE)


def extract_issue_number(*texts: str | None) -> int | None:
    for text in texts:
        if not text:
            continue
        match = _ISSUE_REF_RE.search(text) or _BRANCH_ISSUE_RE.search(text)
        if match:
            return int(match.group(1))
    return None
