import json
from pathlib import Path
from typing import Any, Set

from config import Config
from services.catalog_meta import load_catalog_meta


def is_optional_by_code(code: Any) -> bool:
    """
    Default rule:
    - 851xxxx: optional CS
    - 850xxxx: mandatory CS
    - everything else: optional by default
    """
    s = str(code).strip()
    if s.startswith("851"):
        return True
    if s.startswith("850"):
        return False
    return True     # other degrees default optional


def get_optional_course_codes() -> Set[str]:
    """
    Optional policy (UI-only):
    - Infer from course code code: 850... mandatory, 851... optional, others optional by default
    - Allow override via data_catalog/optional_courses.json
    """
    meta = load_catalog_meta()
    meta_courses = meta.get("courses") or {}

    optional_codes: Set[str] = set()
    for code_str in meta_courses.keys():
        if is_optional_by_code(code_str):
            optional_codes.add(str(code_str))

    opt_path = Path(Config.CATALOG_DIR) / "optional_courses.json"
    if opt_path.exists():
        try:
            data = json.loads(opt_path.read_text(encoding="utf-8"))
            for x in (data.get("optional_codes") or []):
                optional_codes.add(str(x))
        except Exception:
            pass

    return optional_codes
