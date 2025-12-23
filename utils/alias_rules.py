from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv


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

    with p.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        # Expected headers: alias, canonical, notes (notes optional)
        for row in reader:
            if not row:
                continue
            alias = (row.get("alias") or "").strip()
            canonical = (row.get("canonical") or "").strip()
            if not alias or not canonical:
                continue
            mapping[alias] = canonical

    return AliasRules(alias_to_canonical=mapping)