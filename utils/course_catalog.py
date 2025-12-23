from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import csv
import pandas as pd
import re


# Allows to store text even if we dont parse it yet
# note: This does NOT affect DB or solver
@dataclass(frozen=True)
class CatalogCourse:
    code: str
    name: str
    credits: int | None = None

    # NEW (text only, not enforced yet)
    prereq_text: str | None = None
    coreq_text: str | None = None

    # NEW (metadata, UI later)
    study_year: int | None = None
    instructor_name: str | None = None
    weekly_hours: int | None = None
    course_type: str | None = None


def load_catalog(directory: str) -> list[CatalogCourse]:
    p = Path(directory)
    if not p.exists() or not p.is_dir():
        return []

    items: list[CatalogCourse] = []

    for f in p.glob("*.xlsx"):
        try:
            items.extend(_load_xlsx_catalog(f))
        except Exception as e:
            # Skip unreadable Excel files
            print(f"[catalog] Skipping {f.name}: {e}")
            continue
        for f in p.glob("*.csv"):
            items.extend(_load_csv_catalog(f))

    uniq = {(c.code, c.name): c for c in items}
    out = list(uniq.values())
    out.sort(key=lambda c: (c.code, c.name))
    return out


def _load_csv_catalog(f: Path) -> list[CatalogCourse]:
    items = []
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
                    pass

            items.append(
                CatalogCourse(
                    code=code,
                    name=name,
                    credits=credits,
                )
            )
    return items

def _load_xlsx_catalog(f: Path) -> list[CatalogCourse]:
    import pandas as pd

    df = pd.read_excel(f)
    items = []

    def norm(s):
        return str(s).strip() if s is not None else ""

    for _, r in df.iterrows():
        code = norm(r.get("מס.שעור"))
        name = norm(r.get("שם השיעור"))

        if not code or not name:
            continue

        def get_text(col):
            v = r.get(col)
            return norm(v) if pd.notna(v) else None

        def get_int(col):
            v = r.get(col)
            if pd.isna(v):
                return None
            try:
                return int(v)
            except Exception:
                return None

        items.append(
            CatalogCourse(
                code=code,
                name=name,
                credits=get_int("נ.זיכוי"),
                prereq_text=get_text("תיאור ד.קדם"),
                coreq_text=get_text("תיאור ד.מקבילה"),
                study_year=get_int("שנת לימודים"),
                instructor_name=get_text("שם המרצה"),
                weekly_hours=get_int('ש"ש'),
                course_type=get_text("סוג שיעור"),
            )
        )

    return items


def build_catalog_maps(courses: list[CatalogCourse]):
    by_code = {c.code: c for c in courses}
    by_name = {normalize_name(c.name): c.code for c in courses}
    return by_code, by_name


def normalize_name(name: str) -> str:
    return " ".join(name.strip().split())


def normalize_name_key(s: str) -> str:
    s = s.strip()
    s = s.replace('"', "").replace("'", "")
    s = re.sub(r"\s+", " ", s)
    return s

def build_resolver(catalog_courses):
    by_code = {c.code: c for c in catalog_courses}
    by_name = {normalize_name_key(c.name): c.code for c in catalog_courses}

    def resolve(token: str):
        t = normalize_name_key(token)

        # direct code
        if t in by_code:
            return t, token

        # numeric-looking? keep as is; maybe it’s a code not in catalog
        if t.isdigit() and len(t) >= 5:
            return (t if t in by_code else None), token

        # exact name
        code = by_name.get(t)
        if code:
            return code, token

        if is_external_token(t):
            # external prereq   not a degree course to schedule (such as "אנגלית מתקדמים ב")
            return None, token
        
        return None, token

    return resolve

def is_external_token(token: str) -> bool:
    t = normalize_name_key(token)
    return "אנגלית" in t or "עברית" in t or "פטור" in t