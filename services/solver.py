from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

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

    def sat(node: Req, s: int) -> LpVariable:
        nonlocal model      # fixes UnboundLocalError 
        key = (id(node), s)
        if key in sat_cache:
            return sat_cache[key]

        z = LpVariable(
            f"sat_{target_course}_{s}_{id(node) % 10_000_000}",
            lowBound=0,
            upBound=1,
            cat=LpBinary,
        )
        sat_cache[key] = z

        # ---- Leaf ----
        if isinstance(node, ReqLeaf):
            if node.code is None:
                # external/unresolved leaf is ignored at solve-time (new requirement)
                raw = (node.raw or "").strip()
                kind = node.kind if node.kind in ("external", "unresolved") else "unresolved"
                if raw:
                    warnings.append(SolverWarning(course=target_course, raw=raw, kind=kind))
                model += z == 1, f"sat_leaf_ignored_{target_course}_{s}_{id(node)%10_000_000}"
                return z

            if node.code not in allowed_semesters:
                # prereq not in plan/model → ignore but warn
                warnings.append(SolverWarning(course=target_course, raw=node.code, kind="missing_course"))
                model += z == 1, f"sat_leaf_missing_{target_course}_{s}_{id(node)%10_000_000}"
                return z

            before = scheduled_before_expr(x, allowed_semesters, node.code, s)
            # before is 0/1, enforce z == before
            model += z <= before, f"sat_leaf_le_{target_course}_{node.code}_{s}"
            model += z >= before, f"sat_leaf_ge_{target_course}_{node.code}_{s}"
            return z

        # ---- AND ----
        if isinstance(node, ReqAnd):
            items = node.items
            if not items:
                model += z == 1, f"sat_and_empty_{target_course}_{s}_{id(node)%10_000_000}"
                return z
            child_zs = [sat(ch, s) for ch in items]
            for i, cz in enumerate(child_zs):
                model += z <= cz, f"sat_and_le_{target_course}_{s}_{id(node)%10_000_000}_{i}"
            model += z >= lpSum(child_zs) - (len(child_zs) - 1), f"sat_and_ge_{target_course}_{s}_{id(node)%10_000_000}"
            return z

        # ---- OR ----
        if isinstance(node, ReqOr):
            items = node.items
            if not items:
                model += z == 1, f"sat_or_empty_{target_course}_{s}_{id(node)%10_000_000}"
                return z
            child_zs = [sat(ch, s) for ch in items]
            for i, cz in enumerate(child_zs):
                model += z >= cz, f"sat_or_ge_{target_course}_{s}_{id(node)%10_000_000}_{i}"
            model += z <= lpSum(child_zs), f"sat_or_le_{target_course}_{s}_{id(node)%10_000_000}"
            return z

        # fallback safety
        warnings.append(SolverWarning(course=target_course, raw=str(type(node)), kind="unresolved"))
        model += z == 1, f"sat_unknown_{target_course}_{s}_{id(node)%10_000_000}"
        return z

    # Enforce root satisfaction when target is placed in semester s
    for s in allowed_semesters[target_course]:
        model += x[target_course][s] <= sat(prereq_tree, s), f"prereq_ir_{target_course}_{s}"


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


# -----------------------------
# Inputs from DB (legacy offerings/credits, prereqs from catalog IR)
# -----------------------------

def build_inputs_from_plan(plan_id: int) -> Dict:
    """
    Load data from the database for a given DegreePlan and convert it into
    the exact dictionaries that build_model(...) expects.

    rules:
    - Offerings & credits are still legacy (Course + CourseOffering)
    - Prereqs in solver come from catalog prereq_text -> IR at solve-time
    - external/unresolved leaves are ignored by solver but surfaced as warnings
    """
    # Lazy imports to avoid circular imports
    from models.degree_plan import DegreePlan
    from models.course import Course
    from models.plan_constraint import PlanConstraint

    # 1) Get the plan
    plan = DegreePlan.query.get(plan_id)
    if plan is None:
        raise ValueError(f"DegreePlan with id={plan_id} not found")

    # 2) Legacy courses for this plan (still used for offerings + credits this week)
    course_rows: List[Course] = (
        Course.query
        .filter_by(degree_plan_id=plan.id)
        .order_by(Course.id)
        .all()
    )
    if not course_rows:
        raise ValueError(f"No courses defined for plan_id={plan_id}")

    courses: List[str] = [c.code for c in course_rows]
    credits: Dict[str, int] = {c.code: c.credits for c in course_rows}

    # 3) Constraints
    constraints: Optional[PlanConstraint] = PlanConstraint.query.filter_by(
        degree_plan_id=plan.id
    ).first()

    total_semesters = constraints.total_semesters if (constraints and constraints.total_semesters) else 6
    default_max_credits = constraints.max_credits_per_semester if (constraints and constraints.max_credits_per_semester) else 9999

    max_credits_per_semester: Dict[int, int] = {
        s: default_max_credits for s in range(1, total_semesters + 1)
    }

    # 4) Allowed semesters from legacy offerings
    allowed_semesters: Dict[str, List[int]] = {c.code: [] for c in course_rows}
    for c in course_rows:
        for off in c.offerings:
            allowed_semesters[c.code].append(off.semester_number)

    for code in allowed_semesters:
        allowed_semesters[code] = sorted(set(allowed_semesters[code]))

    # 5) Build prereq IR trees from catalog prereq_text
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
