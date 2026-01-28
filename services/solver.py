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
from models.plan_constraint import PlanConstraint
from utils.course_catalog import load_catalog, build_resolver
from utils.external_rules import load_external_rules
from utils.alias_rules import load_aliases_csv
from utils.req_parser import parse_req_text
from services.req_ir import Req, ReqLeaf, ReqAnd, ReqOr
from services.catalog_meta import load_catalog_for_plan
from utils.default_offerings import default_semesters_for_code

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

    # unique run id so names don't collide if this function is called multiple times
    run_id = int(getattr(model, "_ir_prereq_run_id", 0)) + 1
    setattr(model, "_ir_prereq_run_id", run_id)

    # ---- ensure unique PuLP constraint names ----
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
            f"sat_{target_course}_{s}_{run_id}_{node_tag}",
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
                model += z == 1, _uniq(f"sat_leaf_ignored_{target_course}_{s}_{run_id}_{node_tag}")
                return z

            if node.code not in allowed_semesters:
                warnings.append(SolverWarning(course=target_course, raw=node.code, kind="missing_course"))
                model += z == 1, _uniq(f"sat_leaf_missing_{target_course}_{s}_{run_id}_{node_tag}")
                return z

            before = scheduled_before_expr(x, allowed_semesters, node.code, s)
            # before is 0/1, enforce z == before
            model += z <= before, _uniq(f"sat_leaf_le_{target_course}_{node.code}_{s}_{run_id}_{node_tag}")
            model += z >= before, _uniq(f"sat_leaf_ge_{target_course}_{node.code}_{s}_{run_id}_{node_tag}")
            return z

        # ---- AND ----
        if isinstance(node, ReqAnd):
            items = node.items
            if not items:
                model += z == 1, _uniq(f"sat_and_empty_{target_course}_{s}_{run_id}_{node_tag}")
                return z
            child_zs = [sat(ch, s) for ch in items]
            for i, cz in enumerate(child_zs):
                model += z <= cz, _uniq(f"sat_and_le_{target_course}_{s}_{run_id}_{node_tag}_{i}")
            model += z >= lpSum(child_zs) - (len(child_zs) - 1), _uniq(
                f"sat_and_ge_{target_course}_{s}_{run_id}_{node_tag}"
            )
            return z

        # ---- OR ----
        if isinstance(node, ReqOr):
            items = node.items
            if not items:
                model += z == 1, _uniq(f"sat_or_empty_{target_course}_{s}_{run_id}_{node_tag}")
                return z
            child_zs = [sat(ch, s) for ch in items]
            for i, cz in enumerate(child_zs):
                model += z >= cz, _uniq(f"sat_or_ge_{target_course}_{s}_{run_id}_{node_tag}_{i}")
            model += z <= lpSum(child_zs), _uniq(f"sat_or_le_{target_course}_{s}_{run_id}_{node_tag}")
            return z

        # fallback safety
        warnings.append(SolverWarning(course=target_course, raw=str(type(node)), kind="unresolved"))
        model += z == 1, _uniq(f"sat_unknown_{target_course}_{s}_{run_id}_{node_tag}")
        return z

    # Enforce root satisfaction when target is placed in semester s
    for s in allowed_semesters[target_course]:
        model += x[target_course][s] <= sat(prereq_tree, s), _uniq(f"prereq_ir_{target_course}_{s}_{run_id}_")

# -----------------------------
# Model builder
# -----------------------------
# NOTE:
# `minimize_last_semester` comes from PlanConstraint.minimize_last_semester
# (Plan Settings → "Prefer earlier completion when multiple schedules are valid")
def build_model(
    courses: List[str],
    prereq_trees: Dict[str, Req],
    allowed_semesters: Dict[str, List[int]],
    course_credits: Dict[str, int],
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
                    course_credits[c] * x[c][s]
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

    # 4) OBJECTIVE FUNCTION
    # The solver may have many valid schedules that satisfy all constraints
    # (offerings, credits, prerequisites...)
    # This objective defines *how the solver chooses between them*.
    # We support two behaviors, controlled by `minimize_last_semester`:
    #   - unchecked (False): "pack earlier"
    #       → pull courses as far left as possible overall
    #   - checked (True): "finish ASAP, then pack earlier"
    #       → first minimize the *latest semester used*
    #       → then, among those, still prefer earlier placement
    # Lateness = weighted sum of semesters.
    # This encourages placing courses in earlier semesters.
    lateness = lpSum(
        s * x[c][s]
        for c in courses
        for s in allowed_semesters[c]
    )

    if minimize_last_semester:
        # Track the latest semester in which ANY course is scheduled.
        # Every course's chosen semester must be <= last_sem.
        last_sem = LpVariable("last_sem", lowBound=1, cat="Integer")

        for c in courses:
            model += (
                _sem_expr(x, allowed_semesters, c) <= last_sem,
                f"last_sem_after_{c}"
            )

        # Lexicographic objective:
        #   1) Minimize the final semester used (finish ASAP)
        #   2) Tie-break by packing courses earlier within that horizon
        #
        # BIG must dominate any possible lateness value.
        BIG = 10_000
        model += BIG * last_sem + lateness, "finish_early_then_pack"

    else:
        # Default behavior: pack courses earlier overall.
        # This produces predictable, human-friendly schedules.
        model += lateness, "pack_earlier"

    return model, x, warnings


def _default_allowed_semesters_for_code(
    *,
    code: str,
    meta_courses: dict,
    total_semesters: int,
    semesters_per_year: Optional[int],
) -> List[int]:
    """Compatibility wrapper: compute default offerings from metadata + plan structure.

    Policy: if meta has academic_year -> that year's window; else full 1..total_semesters.
    """
    return default_semesters_for_code(
        code=code,
        meta_courses=meta_courses or {},
        total_semesters=total_semesters,
        semesters_per_year=semesters_per_year,
    )

# -----------------------------
# Inputs from DB
# -----------------------------

def build_inputs_from_plan(plan_id: int) -> Dict:
    """
    Load data from the database for a given DegreePlan and convert it into
    the exact dictionaries that build_model(...) expects.
    """
    # Temporary debugging switch for solver input construction.
    debug = False

    def dbg(*args, **kwargs):
        if debug:
            print(*args, **kwargs)

    from types import SimpleNamespace
    from extensions import db
    from models.degree_plan import DegreePlan
    from models.plan_course import PlanCourse
    from models.catalog_course import CatalogCourse
    from models.course import Course
    from models.plan_constraint import PlanConstraint

    plan = DegreePlan.query.get(plan_id)
    if plan is None:
        raise ValueError(f"DegreePlan with id={plan_id} not found")

    constraints = PlanConstraint.query.filter_by(degree_plan_id=plan.id).first()

    total_semesters = (
        constraints.total_semesters if (constraints and constraints.total_semesters) else 6
    )
    default_max_credits = (
        constraints.max_credits_per_semester
        if (constraints and constraints.max_credits_per_semester)
        else 9999
    )

    years = constraints.years if constraints else None
    semesters_per_year = constraints.semesters_per_year if constraints else None

    if years and semesters_per_year:
        total_semesters = int(years) * int(semesters_per_year)
    else:
        total_semesters = int(total_semesters)

    max_credits_per_semester = {
        s: int(default_max_credits) for s in range(1, total_semesters + 1)
    }

    # ---- Plan courses ----
    plan_courses = (
        PlanCourse.query
        .filter_by(plan_id=plan.id)
        .outerjoin(CatalogCourse, PlanCourse.catalog_course_id == CatalogCourse.id)
        .outerjoin(Course, PlanCourse.legacy_course_id == Course.id)
        .order_by(CatalogCourse.code.asc(), Course.code.asc())
        .all()
    )
    if not plan_courses:
        raise ValueError(f"No courses defined for plan_id={plan_id}")

    # ---- Active catalog (PLAN SEED OR GLOBAL) ----
    catalog_meta = load_catalog_for_plan(plan.id)
    meta_courses = catalog_meta.get("courses") or {}

    # ---- Ensure legacy rows for catalog-linked courses ----
    created_any = False
    for pc in plan_courses:
        if pc.legacy_course_id or pc.catalog_course is None:
            continue

        code = str(pc.catalog_course.code).strip()
        legacy = Course.query.filter_by(degree_plan_id=plan.id, code=code).first()
        if legacy is None:
            legacy = Course(
                degree_plan_id=plan.id,
                code=code,
                name=pc.catalog_course.name,
                credits=int(float(pc.catalog_course.credits or 0)),
            )
            db.session.add(legacy)
            db.session.flush()

        pc.legacy_course_id = legacy.id
        created_any = True

    if created_any:
        db.session.commit()

    # ---- Solver course list ----
    courses: List[str] = []
    seen: set[str] = set()
    for pc in plan_courses:
        code = (
            str(pc.catalog_course.code).strip()
            if pc.catalog_course is not None
            else str(pc.legacy_course.code).strip()
        )
        if code and code not in seen:
            seen.add(code)
            courses.append(code)

    if not courses:
        raise ValueError(f"No usable course codes for plan_id={plan_id}")

    # ---- Credits ----
    course_credits: Dict[str, float] = {}
    for pc in plan_courses:
        code = (
            str(pc.catalog_course.code).strip()
            if pc.catalog_course is not None
            else str(pc.legacy_course.code).strip()
        )
        if not code:
            continue

        if pc.catalog_course and pc.catalog_course.credits is not None:
            course_credits[code] = float(pc.catalog_course.credits)
        else:
            course_credits[code] = pc.legacy_course.credits

    for c in courses:
        course_credits.setdefault(c, 0)

    # ---- Allowed semesters ----
    allowed_semesters: Dict[str, List[int]] = {}
    for pc in plan_courses:
        code = (
            str(pc.catalog_course.code).strip()
            if pc.catalog_course is not None
            else str(pc.legacy_course.code).strip()
        )

        sems = []
        if pc.legacy_course:
            for off in pc.legacy_course.offerings:
                try:
                    sems.append(int(off.semester_number))
                except Exception:
                    pass

        if not sems:
            sems = _default_allowed_semesters_for_code(
                code=code,
                meta_courses=meta_courses,
                total_semesters=total_semesters,
                semesters_per_year=semesters_per_year,
            )

        allowed_semesters[code] = sorted(set(sems))

# ------------------------------------------------------------------
# PREREQ RESOLUTION USES *PLAN CATALOG*, NOT GLOBAL
# ------------------------------------------------------------------

    ext_rules = load_external_rules(Config.EXTERNAL_RULES_PATH)
    alias_rules = load_aliases_csv(Config.ALIASES_CSV_PATH)

    # Build resolver catalog from ACTIVE catalog source
    resolver_catalog = []
    for code, m in meta_courses.items():
        if not isinstance(m, dict):
            continue
        resolver_catalog.append(
            SimpleNamespace(
                code=str(code).strip(),
                name=m.get("name"),
                prereq_text=m.get("prereq_text"),
            )
        )

    resolve = build_resolver(
        resolver_catalog,
        external_rules=ext_rules,
        alias_rules=alias_rules,
    )

    catalog_by_code = {c.code: c for c in resolver_catalog}

    prereq_trees: Dict[str, Req] = {}

    for code in courses:
        code_s = str(code).strip()

        m = meta_courses.get(code_s, {})
        text = (m.get("prereq_text") or "").strip() if isinstance(m, dict) else ""

        if not text:
            continue

        tree = parse_req_text(text, resolve)

        if tree is None or (
            isinstance(tree, ReqLeaf) and tree.code is None
        ):
            dbg(f"[PREREQ UNRESOLVED] {code_s}: {text!r} -> {tree}")
            continue

        dbg(f"[PREREQ RESOLVED] {code_s}: {text!r} -> {tree}")
        prereq_trees[code_s] = tree

    dbg("SAMPLE RESOLVER CODES:", list(catalog_by_code.keys())[:20])
    dbg("HAS 8500101?", "8500101" in catalog_by_code)

    return {
        "courses": courses,
        "prereq_trees": prereq_trees,
        "allowed_semesters": allowed_semesters,
        "credits": course_credits,
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
    
    pc = PlanConstraint.query.filter_by(degree_plan_id=plan_id).first()
    if pc and pc.years and pc.semesters_per_year:
        expected = pc.years * pc.semesters_per_year
        if pc.total_semesters != expected:
            raise ValueError(
                f"Invalid plan structure: total_semesters={pc.total_semesters} "
                f"but years ×semesters_per_year={expected}"
            )

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
