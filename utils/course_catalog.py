from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import csv

@dataclass(frozen=True)
class CatalogCourse:
    code: str
    name: str
    credits: int

def load_catalog(directory: str) -> list[CatalogCourse]:
    p = Path(directory)
    if not p.exists() or not p.is_dir():
        return []

    items: list[CatalogCourse] = []

    for f in p.glob("*.csv"):
        with f.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                code = (row.get("code") or row.get("Code") or "").strip()
                name = (row.get("name") or row.get("Name") or row.get("title") or row.get("Title") or "").strip()
                credits_raw = (row.get("credits") or row.get("Credits") or "").strip()
                if not code or not name or not credits_raw:
                    continue
                try:
                    credits = int(float(credits_raw))
                except ValueError:
                    continue
                items.append(CatalogCourse(code=code, name=name, credits=credits))

    uniq = {(c.code, c.name, c.credits): c for c in items}
    out = list(uniq.values())
    out.sort(key=lambda c: (c.code, c.name, c.credits))
    return out
