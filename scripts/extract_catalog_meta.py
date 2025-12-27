from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from utils.course_catalog import load_catalog


BASE_DIR = Path(__file__).resolve().parents[1]
CATALOG_DIR = BASE_DIR / "data_catalog"
OUT_PATH = CATALOG_DIR / "catalog_meta.json"


def _to_int_year(x: Any) -> Optional[int]:
    if x is None:
        return None
    try:
        return int(x)
    except Exception:
        return None


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _normalize_lesson_type(raw: Any) -> Optional[str]:
    s = (str(raw).strip() if raw is not None else "")
    if not s:
        return None

    t = s.replace(" ", "")

    # match your XLSX meanings keep it simple 
    if "תרגול" in t and ("הרצאה" in t or "שיעור" in t):
        return "lesson+practice"
    if "הרצאה" in t or "שיעור" in t:
        return "lesson"
    if "תרגול" in t:
        return "practice"
    if "מעבדה" in t:
        return "lab"
    if "סמינר" in t:
        return "seminar"

    return "other"


def main() -> None:
    catalog = load_catalog(str(CATALOG_DIR))

    courses: dict[str, dict[str, Any]] = {}
    for item in catalog:
        code = str(item.code)

        courses[code] = {
            "degree_tags": ["CS"],

            "academic_year": _to_int_year(item.study_year),
            "lecturer": item.instructor_name or None,
            "weekly_hours": _to_float(item.weekly_hours),
            "lesson_type": _normalize_lesson_type(item.course_type),
            "coreq_text": item.coreq_text or None,

            "raw": {
                "academic_year": item.study_year,
                "lecturer": item.instructor_name,
                "weekly_hours": item.weekly_hours,
                "lesson_type": item.course_type,
                "coreq_text": item.coreq_text,
            },
        } 
        

    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {"folder": str(CATALOG_DIR.relative_to(BASE_DIR))},
        "degrees": {"CS": {"label": "Computer Science", "active": True}},
        "courses": courses,
    }

    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH} with {len(courses)} courses.")


if __name__ == "__main__":
    main()
