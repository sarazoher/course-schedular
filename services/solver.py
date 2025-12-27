from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from pulp import (
    LpProblem,
    LpMinimize,
    LpVariable,
    lpSum,
    LpStatus,
    PULP_CBC_CMD,
    LpBinary,
)

# ↓ import granting access to IR + parsing entry point
from config import Config
from utils.course_catalog import load_catalog, build_resolver
from utils.external_rules import load_external_rules
from utils.alias_rules import load_aliases_csv
from utils.req_parser import parse_req_text
from services.req_ir import Req, ReqLeaf, ReqAnd, ReqOr

# -----------------------------
# Warnings container
# -----------------------------
# note: for the moment, it returned in solver output JSON, integrating UI display later

@dataclass
class SolverWarning:
    course: str   # course being scheduled
    raw: str      # raw token / leaf raw (or missing code)
    kind: str     # "external" | "unresolved" | "missing_course"


# -----------------------------
# Helpers
# -----------------------------

def _chosen_semester(
    x: Dict[str, Dict[int, LpVariable]],
    allowed_semesters: Dict[str, List[int]],
    code: str,
) -> Optional[int]:
    for s in allowed_semesters[code]:
        v = x[code][s].value()
        if v is not None and v > 0.5:
            return s
    return None


def _sem_expr(
    x: Dict[str, Dict[int, LpVariable]],
    allowed_semesters: Dict[str, List[int]],
    code: str,
):
    # “semester number” linear expression for code
    return lpSum(s * x[code][s] for s in allowed_semesters[code])


def scheduled_before_expr(
    x: Dict[str, Dict[int, LpVariable]],
    allowed_semesters: Dict[str, List[int]],
    course_code: str,
    s: int,
):
    """
    Returns expression that equals 1 iff course_code is scheduled in a semester < s.
    Works because each course is forced to be scheduled exactly once.
    """
    return lpSum(
        x[course_code][t]
        for t in allowed_semesters[course_code]
        if t < s
    )


# -----------------------------
# IR -> MILP constraints
# -----------------------------

def add_ir_prereq_constraints(
    model: LpProblem,
    x: Dict[str, Dict[int, LpVariable]],
    *,
    target_course: str,
    prereq_tree: Req,
    allowed_semesters: Dict[str, List[int]],
    warnings: List[SolverWarning],
):
    """
    Enforce prereq_tree for target_course:
      if x[target_course][s] == 1, then prereq_tree must be satisfied before s.

    Leaves:
      - internal (code != None): enforce scheduling-before
      - external/unresolved (code == None): ignore but warn
      - missing_course (internal code not in model): ignore but warn
    """
    sat_cache: Dict[Tuple[int, int], LpVariable] = {}

    # ---- Ensure unique PuLP constraint names ----
    _name_counts: Dict[str, int] = {}

    def _uniq(name: str) -> str:
        """PuLP requires unique constraint names across the whole model."""
        n = _name_counts.get(name, 0)
        _name_counts[name] = n + 1
        return name if n == 0 else f"{name}__{n}"

    def sat(node: Req, s: int) -> LpVariable:
        nonlocal model
        key = (id(node), s)
        if key in sat_cache:
            return sat_cache[key]

        node_tag = id(node) % 10_000_000  # stable-ish short tag per node instance

        z = LpVariable(
            f"sat_{target_course}_{s}_{node_tag}",
            lowBound=0,
            upBound=1,
            cat=LpBinary,
        )
        sat_cache[key] = z

        # ---- Leaf ----
        if isinstance(node, ReqLeaf):
            if node.code is None:
                raw = (node.raw or "").strip()
                kind = node.kind if node.kind in ("external", "unresolved") else "unresolved"
                if raw:
                    warnings.append(SolverWarning(course=target_course, raw=raw, kind=kind))
                model += z == 1, _uniq(f"sat_leaf_ignored_{target_course}_{s}_{node_tag}")
                return z

            if node.code not in allowed_semesters:
                warnings.append(SolverWarning(course=target_course, raw=node.code, kind="missing_course"))
                model += z == 1, _uniq(f"sat_leaf_missing_{target_course}_{s}_{node_tag}")
                return z

            before = scheduled_before_expr(x, allowed_semesters, node.code, s)
            # before is 0/1, enforce z == before
            # ---- Include node_tag AND run through _uniq ----
            model += z <= before, _uniq(f"sat_leaf_le_{target_course}_{node.code}_{s}_{node_tag}")
            model += z >= before, _uniq(f"sat_leaf_ge_{target_course}_{node.code}_{s}_{node_tag}")
            return z

        # ---- AND ----
        if isinstance(node, ReqAnd):
            items = node.items
            if not items:
                model += z == 1, _uniq(f"sat_and_empty_{target_course}_{s}_{node_tag}")
                return z
            child_zs = [sat(ch, s) for ch in items]
            for i, cz in enumerate(child_zs):
                model += z <= cz, _uniq(f"sat_and_le_{target_course}_{s}_{node_tag}_{i}")
            model += z >= lpSum(child_zs) - (len(child_zs) - 1), _uniq(
                f"sat_and_ge_{target_course}_{s}_{node_tag}"
            )
            return z

        # ---- OR ----
        if isinstance(node, ReqOr):
            items = node.items
            if not items:
                model += z == 1, _uniq(f"sat_or_empty_{target_course}_{s}_{node_tag}")
                return z
            child_zs = [sat(ch, s) for ch in items]
            for i, cz in enumerate(child_zs):
                model += z >= cz, _uniq(f"sat_or_ge_{target_course}_{s}_{node_tag}_{i}")
            model += z <= lpSum(child_zs), _uniq(f"sat_or_le_{target_course}_{s}_{node_tag}")
            return z

        # fallback safety
        warnings.append(SolverWarning(course=target_course, raw=str(type(node)), kind="unresolved"))
        model += z == 1, _uniq(f"sat_unknown_{target_course}_{s}_{node_tag}")
        return z

    # Enforce root satisfaction when target is placed in semester s
    for s in allowed_semesters[target_course]:
        model += x[target_course][s] <= sat(prereq_tree, s), _uniq(f"prereq_ir_{target_course}_{s}")


# -----------------------------
# Model builder
# -----------------------------

def build_model(
    courses: List[str],
    prereq_trees: Dict[str, Req],
    allowed_semesters: Dict[str, List[int]],
    credits: Dict[str, int],
    max_credits_per_semester: Dict[int, int],
    *,
    use_credit_limits: bool,
    use_prereqs_ir: bool,
    minimize_last_semester: bool,
):
    """
    core model builder.

    - courses: solver IDs (course codes)
    - prereq_trees: course_code -> IR tree (ReqLeaf/ReqAnd/ReqOr)
    - allowed_semesters: course_code -> [semester_number...]
    - credits: course_code -> int
    - max_credits_per_semester: semester_number -> max credits

    Returns: (model, x, warnings)
    """
    model = LpProblem("CourseScheduler", LpMinimize)

    # decision vars: x[c,s] in {0,1}
    x: Dict[str, Dict[int, LpVariable]] = {}
    for c in courses:
        sems = allowed_semesters.get(c, [])
        if not sems:
            # This should be caught by pre-solve guardrails elsewhere.
            # Keep it explicit: solver cannot place a course with no offerings.
            raise ValueError(f"Course {c} has no allowed semesters (offerings).")
        x[c] = {}
        for s in sems:
            x[c][s] = LpVariable(f"x_{c}_{s}", lowBound=0, upBound=1, cat=LpBinary)

    # 1) always: each course exactly once
    for c in courses:
        model += lpSum(x[c][s] for s in allowed_semesters[c]) == 1, f"one_sem_{c}"

    semesters = sorted({s for sems in allowed_semesters.values() for s in sems})

    # 2) optional: CREDIT LIMITS
    if use_credit_limits:
        for s in semesters:
            model += (
                lpSum(
                    credits[c] * x[c][s]
                    for c in courses
                    if s in allowed_semesters[c]
                )
                <= max_credits_per_semester.get(s, 9999)
            ), f"max_credits_sem_{s}"

    # 3) optional: PREREQS (IR)
    warnings: List[SolverWarning] = []
    if use_prereqs_ir:
        for c in courses:
            tree = prereq_trees.get(c)
            if tree is None:
                continue
            add_ir_prereq_constraints(
                model,
                x,
                target_course=c,
                prereq_tree=tree,
                allowed_semesters=allowed_semesters,
                warnings=warnings,
            )

    # 4) objective
    if minimize_last_semester:
        last_sem = LpVariable("last_sem", lowBound=1, cat="Integer")
        for c in courses:
            model += _sem_expr(x, allowed_semesters, c) <= last_sem, f"last_sem_after_{c}"
        model += last_sem, "minimize_last_semester"
    else:
        model += lpSum(
            s * x[c][s] for c in courses for s in allowed_semesters[c]
        ), "minimize_sum_semesters"

    return model, x, warnings


def _default_allowed_semesters_for_code(
    *,
    code: str,
    meta_courses: dict,
    total_semesters: int,
    semesters_per_year: Optional[int],
) -> List[int]:
    """
    Safe default offerings when a course has no explicit offerings yet.
    Policy:
      - if metadata has academic_year and semesters_per_year is known (or assumed 2), allow that year's semester window
      - otherwise allow all semesters (1..total_semesters)
    """
    sp = semesters_per_year or 2  # safe default if user didn't configure plan structure
    m = meta_courses.get(str(code), {})
    if not isinstance(m, dict):
        m = {}

    y_raw = m.get("academic_year")
    try:
        y = int(y_raw) if y_raw is not None and str(y_raw).strip() != "" else None
    except Exception:
        y = None

    if y is None or y < 1:
        return list(range(1, total_semesters + 1))

    start = (y - 1) * sp + 1
    end = min(total_semesters, y * sp)
    if start > total_semesters:
        return list(range(1, total_semesters + 1))

    return list(range(start, end + 1))


# -----------------------------
# Inputs from DB 
# -----------------------------

def build_inputs_from_plan(plan_id: int) -> Dict:
    """
    Load data from the database for a given DegreePlan and convert it into
    the exact dictionaries that build_model(...) expects.

    - Courses/credits come from PlanCourse -> CatalogCourse (source of truth)
    - If a PlanCourse isn't linked to a legacy Course yet, we auto-create the legacy Course row
      and default offerings, then link it (so existing UI keeps working).
    - Prereqs in solver come from catalog prereq_text -> IR at solve-time (unchanged)
    """
    # Lazy imports to avoid circular imports
    from extensions import db
    from models.degree_plan import DegreePlan
    from models.plan_course import PlanCourse
    from models.catalog_course import CatalogCourse
    from models.course import Course
    from models.course_offering import CourseOffering
    from models.plan_constraint import PlanConstraint
    from services.catalog_meta import load_catalog_meta

    plan = DegreePlan.query.get(plan_id)
    if plan is None:
        raise ValueError(f"DegreePlan with id={plan_id} not found")

    constraints: Optional[PlanConstraint] = PlanConstraint.query.filter_by(
        degree_plan_id=plan.id
    ).first()

    total_semesters = constraints.total_semesters if (constraints and constraints.total_semesters) else 6
    default_max_credits = (
        constraints.max_credits_per_semester
        if (constraints and constraints.max_credits_per_semester)
        else 9999
    )
    semesters_per_year = constraints.semesters_per_year if constraints else None

    max_credits_per_semester: Dict[int, int] = {
        s: default_max_credits for s in range(1, total_semesters + 1)
    }

    # ---- source of truth: PlanCourse -> CatalogCourse ----
    plan_courses = (
        PlanCourse.query
        .filter_by(plan_id=plan.id)
        .join(CatalogCourse, PlanCourse.catalog_course_id == CatalogCourse.id)
        .order_by(CatalogCourse.code.asc())
        .all()
    )
    if not plan_courses:
        raise ValueError(f"No courses defined for plan_id={plan_id}")

    # metadata used only for default offerings window
    meta = load_catalog_meta()
    meta_courses = meta.get("courses") or {}

    # ---- Ensure every PlanCourse has a legacy Course row ----
    created_any = False
    for pc in plan_courses:
        if pc.legacy_course_id:
            continue

        code = str(pc.catalog_course.code).strip()
        name = pc.catalog_course.name
        cat_credits = pc.catalog_course.credits

        # legacy Course.credits is Integer in your model, so store safely.
        # (solver can still use float credits from catalog, DB legacy stays int)
        legacy_credits_int = 0
        try:
            if cat_credits is not None:
                legacy_credits_int = int(float(cat_credits))
        except Exception:
            legacy_credits_int = 0

        legacy = Course.query.filter_by(degree_plan_id=plan.id, code=code).first()
        if legacy is None:
            legacy = Course(
                degree_plan_id=plan.id,
                code=code,
                name=name,
                credits=legacy_credits_int,
                difficulty=None,
            )
            db.session.add(legacy)
            db.session.flush()

            # default offerings (only for brand-new legacy course)
            allowed = _default_allowed_semesters_for_code(
                code=code,
                meta_courses=meta_courses,
                total_semesters=total_semesters,
                semesters_per_year=semesters_per_year,
            )
            for s in allowed:
                db.session.add(CourseOffering(course_id=legacy.id, semester_number=int(s)))

        pc.legacy_course_id = legacy.id
        created_any = True

    if created_any:
        db.session.commit()

    # ---- Build solver inputs from PlanCourse ----
    courses: List[str] = [str(pc.catalog_course.code).strip() for pc in plan_courses]

    # credits: prefer catalog float, fall back to legacy int if missing
    credits: Dict[str, Any] = {}
    for pc in plan_courses:
        code = str(pc.catalog_course.code).strip()
        if pc.catalog_course.credits is not None:
            credits[code] = float(pc.catalog_course.credits)
        elif pc.legacy_course is not None:
            credits[code] = pc.legacy_course.credits
        else:
            credits[code] = 0

    # allowed semesters: from offerings if present, otherwise default window
    allowed_semesters: Dict[str, List[int]] = {}
    for pc in plan_courses:
        code = str(pc.catalog_course.code).strip()
        sems: List[int] = []
        if pc.legacy_course is not None:
            for off in pc.legacy_course.offerings:
                sems.append(int(off.semester_number))

        sems = sorted(set(sems))
        if not sems:
            sems = _default_allowed_semesters_for_code(
                code=code,
                meta_courses=meta_courses,
                total_semesters=total_semesters,
                semesters_per_year=semesters_per_year,
            )

        allowed_semesters[code] = sems

    # ---- Build prereq IR trees from catalog prereq_text (unchanged) ----
    catalog = load_catalog(Config.CATALOG_DIR)
    ext_rules = load_external_rules(Config.EXTERNAL_RULES_PATH)
    alias_rules = load_aliases_csv(Config.ALIASES_CSV_PATH)
    resolve = build_resolver(catalog, external_rules=ext_rules, alias_rules=alias_rules)

    catalog_by_code = {c.code: c for c in catalog}
    prereq_trees: Dict[str, Req] = {}

    for code in courses:
        cat = catalog_by_code.get(code)
        if not cat:
            continue
        text = (getattr(cat, "prereq_text", None) or "").strip()
        if not text:
            continue
        tree = parse_req_text(text, resolve)
        if tree is not None:
            prereq_trees[code] = tree

    return {
        "courses": courses,
        "prereq_trees": prereq_trees,
        "allowed_semesters": allowed_semesters,
        "credits": credits,
        "max_credits_per_semester": max_credits_per_semester,
    }


# -----------------------------
# Solve wrapper (returns JSON-ready payload; persistence handled by route/service)
# -----------------------------

def solve_plan(
    plan_id: int,
    *,
    use_credit_limits: bool = True,
    use_prereqs_ir: bool = True,
    minimize_last_semester: bool = True,
    msg: bool = False,
) -> Dict:
    """
    Solve a plan and return a JSON-serializable payload:
      - status
      - schedule
      - warnings

    Persisting into PlanSolution is intentionally NOT done here.
    """
    inputs = build_inputs_from_plan(plan_id)

    model, x, warnings = build_model(
        inputs["courses"],
        inputs["prereq_trees"],
        inputs["allowed_semesters"],
        inputs["credits"],
        inputs["max_credits_per_semester"],
        use_credit_limits=use_credit_limits,
        use_prereqs_ir=use_prereqs_ir,
        minimize_last_semester=minimize_last_semester,
    )

    model.solve(PULP_CBC_CMD(msg=msg))
    status = LpStatus[model.status]

    schedule: Dict[str, Optional[int]] = {}
    for c in inputs["courses"]:
        schedule[c] = _chosen_semester(x, inputs["allowed_semesters"], c)

    return {
        "status": status,
        "schedule": schedule,
        "warnings": [w.__dict__ for w in warnings],
    }
