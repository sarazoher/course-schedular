from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class ExternalRules:
    """Rules for classifying prerequisite tokens as external requirements.

    This is solve-time only. Keeping rules in a file makes the project portable
    across different catalogs/universities without editing Python code.
    """

    exact: set[str]
    patterns: list[re.Pattern[str]]


def load_external_rules(path: str) -> ExternalRules:
    """Load external classification rules from a text file.

    Supported formats (one per line):
      - comments: lines starting with '#'
      - blank lines ignored
      - exact:<token>  (exact match after normalization)
      - re:<regex>     (regex searched after normalization)
      - <regex>        (treated as regex if no prefix)
    """

    p = Path(path)
    exact: set[str] = set()
    patterns: list[re.Pattern[str]] = []

    if not p.exists():
        return ExternalRules(exact=exact, patterns=patterns)

    for raw_line in p.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("exact:"):
            exact.add(line[len("exact:") :].strip())
            continue

        if line.startswith("re:"):
            rx = line[len("re:") :].strip()
            patterns.append(re.compile(rx))
            continue

        # Default: treat as regex for convenience.
        patterns.append(re.compile(line))

    return ExternalRules(exact=exact, patterns=patterns)