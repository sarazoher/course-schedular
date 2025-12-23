from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import re
import pandas as pd

from utils.external_rules import ExternalRules
from utils.alias_rules import AliasRules


# Allows storing text even if we don't parse it yet
# Note: This does NOT affect DB or solver
@dataclass(frozen=True)
class CatalogCourse:
    code: str
    name: str
    credits: int | None = None

    # text only (not enforced yet)
    prereq_text: str | None = None
    coreq_text: str | None = None

    # metadata (UI later)
    study_year: int | None = None
    instructor_name: str | None = None
    weekly_hours: int | None = None
    course_type: str | None = None


def normalize_name_key(s: str) -> str:
    s = str(s or "").strip()
    s = s.replace('"', "").replace("'", "")
    s = re.sub(r"\s+", " ", s)
    return s


def load_catalog(directory: str) -> list[CatalogCourse]:
    p = Path(directory)
    if not p.exists() or not p.is_dir():
        return []

    items: list[CatalogCourse] = []

    # Load Excel files
    for f in p.glob("*.xlsx"):
        try:
            items.extend(_load_xlsx_catalog(f))
        except Exception as e:
            # Skip unreadable Excel files
            print(f"[catalog] Skipping {f.name}: {e}")

    # Load CSV files (NOT nested under the xlsx loop)
    for f in p.glob("*.csv"):
        try:
            items.extend(_load_csv_catalog(f))
        except Exception as e:
            print(f"[catalog] Skipping {f.name}: {e}")

    # De-dup
    uniq = {(c.code, c.name): c for c in items}
    out = list(uniq.values())
    out.sort(key=lambda c: (c.code, c.name))
    return out


def _load_csv_catalog(f: Path) -> list[CatalogCourse]:
    items: list[CatalogCourse] = []
    with f.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            code = (row.get("code") or row.get("Code") or "").strip()
            name = (row.get("name") or row.get("Name") or "").strip()
            credits_raw = (row.get("credits") or row.get("Credits") or "").strip()

            if not code or not name:
                continue

            credits = None
            if credits_raw:
                try:
                    credits = int(float(credits_raw))
                except ValueError:
                    credits = None

            items.append(CatalogCourse(code=code, name=name, credits=credits))
    return items


def _load_xlsx_catalog(f: Path) -> list[CatalogCourse]:
    df = pd.read_excel(f)
    items: list[CatalogCourse] = []

    def norm(v) -> str:
        return normalize_name_key(v)

    def get_text(r, col: str) -> str | None:
        v = r.get(col)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = norm(v)
        return s if s else None

    def get_int(r, col: str) -> int | None:
        v = r.get(col)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        try:
            return int(float(v))
        except Exception:
            return None

    for _, r in df.iterrows():
        code = norm(r.get("מס.שעור"))
        name = norm(r.get("שם השיעור"))

        if not code or not name:
            continue

        items.append(
            CatalogCourse(
                code=code,
                name=name,
                credits=get_int(r, "נ.זיכוי"),
                prereq_text=get_text(r, "תיאור ד.קדם"),
                coreq_text=get_text(r, "תיאור ד.מקבילה"),
                study_year=get_int(r, "שנת לימודים"),
                instructor_name=get_text(r, "שם המרצה"),
                weekly_hours=get_int(r, 'ש"ש'),
                course_type=get_text(r, "סוג שיעור"),
            )
        )

    return items


def build_catalog_maps(courses: list[CatalogCourse]):
    by_code = {c.code: c for c in courses}
    by_name = {normalize_name_key(c.name): c.code for c in courses}
    return by_code, by_name


def build_resolver(
    catalog_courses: list[CatalogCourse],
    external_rules: ExternalRules | None = None,
    alias_rules: AliasRules | None = None,
):
    by_code = {c.code: c for c in catalog_courses}
    by_name = {normalize_name_key(c.name): c.code for c in catalog_courses}

    # Normalize alias keys once for stable matching
    alias_map_norm: dict[str, str] = {}
    if alias_rules:
        for a, canon in alias_rules.alias_to_canonical.items():
            alias_map_norm[normalize_name_key(a)] = (canon or "").strip()

    def resolve(token: str):
        t = normalize_name_key(token)

        # 0) Alias mapping (before any other resolution)
        # Alias can point to a NAME, fallback -> CODE.
        canon = alias_map_norm.get(t)
        if canon:
            canon_norm = normalize_name_key(canon)

            # If canonical looks like a pure code, treat as code
            if canon_norm.isdigit():
                return (
                    (canon_norm if canon_norm in by_code else None),
                    token,
                    ("internal" if canon_norm in by_code else "unresolved"),
                )

            # Otherwise treat canonical as a course name
            code = by_name.get(canon_norm)
            if code:
                return code, token, "internal"
            return None, token, "unresolved"

        # 1) Direct code match
        if t in by_code:
            return t, token, "internal"

        # 2) Numeric-looking code that isn't in catalog
        if t.isdigit() and len(t) >= 5:
            return None, token, "unresolved"

        # 3) Exact name match
        code = by_name.get(t)
        if code:
            return code, token, "internal"

        # 4) External requirement
        if external_rules and is_external_token(t, external_rules):
            return None, token, "external"

        return None, token, "unresolved"

    return resolve

    print("CHECK EXTERNAL:", repr(t))


def is_external_token(token: str, rules: ExternalRules) -> bool:
    t = normalize_name_key(token)
    if t in rules.exact:
        return True
    return any(rx.search(t) for rx in rules.patterns)
