"""
regen_offerings.py — Repair bad / missing course offerings for a plan

Recomputes and rewrites CourseOffering rows for a single DegreePlan.

What it does:
- Reads plan structure from PlanConstraint (total_semesters, semesters_per_year)
- Uses catalog metadata (academic_year per course, if available)
- For each plan-scoped Course:
    - Computes the desired semester numbers
    - Deletes existing CourseOffering rows if they differ
    - Inserts the corrected offerings

Important assumptions:
- Operates ONLY on legacy plan-scoped Course rows
  (Course.degree_plan_id = plan_id)
- Plans that use PlanCourse / CatalogCourse without legacy Course rows
  will not be modified.

Offering rules:
- Missing or invalid academic_year → course offered in all semesters
- academic_year = Y → offered in that year's semesters based on
  semesters_per_year
- If computed semesters fall out of range → fallback to all semesters

Safety notes:
- This script writes directly to the database.
- Offerings are deleted and recreated per course if mismatched.
- Recommended to run on a backup or test DB first.

Usage:
    python scripts/regen_offerings.py
    (edit plan_id in __main__ before running)
"""

import os
import sys

# Make project root importable (so `import app` works when running from /scripts)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import db
from models.course import Course
from models.course_offering import CourseOffering
from models.plan_constraint import PlanConstraint
from services.catalog_meta import load_catalog_meta


def regen_offerings(plan_id: int) -> None:
    """
    Recompute and repair CourseOffering rows for a single plan.

    Only affects courses belonging to the given plan_id and only
    rewrites offerings when the computed semesters differ.
    """
    pc = PlanConstraint.query.filter_by(degree_plan_id=plan_id).first()
    if pc is None:
        raise ValueError(f"PlanConstraint missing for plan_id={plan_id}")

    total = int(pc.total_semesters or 6)
    sp = int(pc.semesters_per_year or 2)

    meta = load_catalog_meta()
    meta_courses = meta.get("courses") or {}

    courses = Course.query.filter_by(degree_plan_id=plan_id).all()

    changed = 0
    for c in courses:
        m = meta_courses.get(str(c.code).strip(), {})
        year_raw = m.get("academic_year") if isinstance(m, dict) else None
        try:
            year = int(year_raw) if year_raw is not None else None
        except Exception:
            year = None

        if not year or year < 1:
            desired = list(range(1, total + 1))
        else:
            start = (year - 1) * sp + 1
            desired = [s for s in range(start, start + sp) if 1 <= s <= total]
            if not desired:
                desired = list(range(1, total + 1))

        existing = sorted({int(o.semester_number) for o in c.offerings})
        if existing == desired:
            continue

        # rewrite offerings for THIS course (plan-local)
        CourseOffering.query.filter_by(course_id=c.id).delete()
        for s in desired:
            db.session.add(CourseOffering(course_id=c.id, semester_number=int(s)))

        changed += 1

    db.session.commit()
    print(f"regen_offerings done for plan {plan_id}. courses changed: {changed}")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        regen_offerings(plan_id=1)  # <-- change plan id here