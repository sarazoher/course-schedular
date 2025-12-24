from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import io 

@dataclass(frozen=True)
class AliasRules:
    """
    Solve-time only mapping from a prereq token alias -> canonical course identifier.

    canonical can be:
      - a course code (digits), OR
      - a canonical course name as it appears in the catalog.
    """

    alias_to_canonical: dict[str, str]


def load_aliases_csv(path: str) -> AliasRules:
    p = Path(path)
    mapping: dict[str, str] = {}

    if not p.exists():
        return AliasRules(alias_to_canonical=mapping)

    # Read and pre-filter lines so DictReader sees a real header row.
    raw_lines = p.read_text(encoding="utf-8").splitlines()
    cleaned_lines: list[str] = []
    for line in raw_lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        cleaned_lines.append(line)

    if not cleaned_lines:
        return AliasRules(alias_to_canonical=mapping)

    with io.StringIO("\n".join(cleaned_lines)) as f:
        reader = csv.DictReader(f)

        # Normalize fieldnames (strip whitespace, lower-case)
        if reader.fieldnames:
            reader.fieldnames = [fn.strip().lower() for fn in reader.fieldnames]

        for row in reader:
            if not row:
                continue
            alias = (row.get("alias") or "").strip()
            canonical = (row.get("canonical") or "").strip()
            if not alias or not canonical:
                continue
            mapping[alias] = canonical

    return AliasRules(alias_to_canonical=mapping)