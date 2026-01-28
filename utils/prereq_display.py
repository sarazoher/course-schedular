from __future__ import annotations

from typing import Dict, List, Tuple

_PUNCT = ",;:.()[]{}"


def extract_recognized_courses(
    text: str | None,
    course_name_by_code: Dict[str, str],
) -> List[Tuple[str, str]]:
    """Display-only helper.

    Given free-text prereq/coreq strings, return a stable list of (code, name)
    pairs for tokens that exactly match known course codes.

    This is intentionally *not* solver logic. It's only for UI readability.
    """
    if not text or not course_name_by_code:
        return []

    seen: set[str] = set()
    out: List[Tuple[str, str]] = []

    for raw in str(text).split():
        tok = raw.strip(_PUNCT).strip()
        if not tok or tok in seen:
            continue

        name = course_name_by_code.get(tok)
        if name:
            seen.add(tok)
            out.append((tok, name))

    return out