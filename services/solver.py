from typing import Dict, List
from pulp import (
    LpProblem,
    LpMinimize,
    LpVariable,
    lpSum,
    LpStatus,
    PULP_CBC_CMD,
)


def build_model(
    courses: List[str],
    prereqs: Dict[str, List[str]],
    allowed_semesters: Dict[str, List[int]],
    credits: Dict[str, int],
    max_credits_per_semester: Dict[int, int],
    *,
    use_credit_limits: bool,
    use_prereqs: bool,
    minimize_last_semester: bool,
):

    """
    Core model builder.
    Well use the boolean flags above to decide which pieces are active.
    """

    model = LpProblem("CourseScheduler", LpMinimize)

    # decision vars: x[c,s] in {0,1}
    x: Dict[str, Dict[int, LpVariable]] = {}
    for c in courses:
        x[c] = {}
        for s in allowed_semesters[c]:
            x[c][s] = LpVariable(f"x_{c}_{s}", lowBound=0, upBound=1, cat="Binary")

    # helper: "semester of course c" as linear expression
    def sem_expr(c: str):
        return lpSum(s * x[c][s] for s in allowed_semesters[c])

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

    # 3) optional: PREREQS
    if use_prereqs:
        for c in courses:
            for p in prereqs.get(c, []):
                model += sem_expr(p) + 1 <= sem_expr(c), f"prereq_{p}_before_{c}"

    # 4) objective
    if minimize_last_semester:
        # minimize the latest semester used
        last_sem = LpVariable("last_sem", lowBound=1, cat="Integer")
        for c in courses:
            model += sem_expr(c) <= last_sem, f"last_sem_after_{c}"
        model += last_sem, "minimize_last_semester"
    else:
        # simple "earlier is better" objective
        model += lpSum(
            s * x[c][s] for c in courses for s in allowed_semesters[c]
        ), "minimize_sum_semesters"

    return model, x



def build_inputs_from_plan(plan_id: int) -> Dict:
    """
    Load data from the database for a given DegreePlan and convert it into
    the exact dictionaries that build_model(...) expects.

    Returns a dict with keys:
        - courses: List[str]                  # course codes (solver IDs)
        - prereqs: Dict[str, List[str]]       # course_code -> [prereq_code, ...]
        - credits: Dict[str, int]
        - max_credits_per_semester: Dict[int, int]
    """
    # Lazy imports to avoid circular imports with app/__init__
    from models.degree_plan import DegreePlan
    from models.course import Course
    from models.course_offering import CourseOffering
    from models.prerequisite import Prerequisite
    from models.plan_constraint import PlanConstraint

    # 1) Get the plan (service layer → use .get + ValueError, not get_or_404)
    plan = DegreePlan.query.get(plan_id)
    if plan is None:
        raise ValueError(f"DegreePlan with id={plan_id} not found")

    # 2) Courses for this plan
    course_rows: List[Course] = (
        Course.query
        .filter_by(degree_plan_id=plan.id)
        .order_by(Course.id)
        .all()
    )
    if not course_rows:
        raise ValueError(f"No courses defined for plan_id={plan_id}")

    # We'll use course.code as the solver's ID
    courses: List[str] = [c.code for c in course_rows]
    code_by_id: Dict[int, str] = {c.id: c.code for c in course_rows}
    credits: Dict[str, int] = {c.code: c.credits for c in course_rows}

    # 3) Plan constraints: total_semesters + global max_credits_per_semester
    constraints: PlanConstraint | None = PlanConstraint.query.filter_by(
        degree_plan_id=plan.id
    ).first()

    if constraints and constraints.total_semesters:
        total_semesters = constraints.total_semesters
    else:
        # fallback if not set yet – we can tune later
        total_semesters = 6

    if constraints and constraints.max_credits_per_semester:
        default_max_credits = constraints.max_credits_per_semester
    else:
        # fallback: effectively no limit
        default_max_credits = 9999

    # max_credits_per_semester dict: same value for each semester for now
    max_credits_per_semester: Dict[int, int] = {
        s: default_max_credits for s in range(1, total_semesters + 1)
    }

    # 4) Allowed semesters from CourseOffering
    #
    # CourseOffering has:
    #    course_id
    #    semester_number
    #
    # Each Course row has .offerings backref (because of the relationship).
    allowed_semesters: Dict[str, List[int]] = {c.code: [] for c in course_rows}

    for c in course_rows:
        for off in c.offerings:
            # Just trust the semester_number as given
            allowed_semesters[c.code].append(off.semester_number)

    # If there are no offerings at all, or some courses have no offerings,
    # allow them in all semesters 1..total_semesters.
    any_offerings = any(allowed_semesters[c] for c in allowed_semesters)
    if not any_offerings:
        # nothing defined at all → everything allowed everywhere
        for c in courses:
            allowed_semesters[c] = list(range(1, total_semesters + 1))
    else:
        # fill gaps only for courses that had no offerings
        for c in courses:
            if not allowed_semesters[c]:
                allowed_semesters[c] = list(range(1, total_semesters + 1))

    # Sort & deduplicate for sanity
    for code in allowed_semesters:
        allowed_semesters[code] = sorted(set(allowed_semesters[code]))

    # 5) Prereqs from Prerequisite table
    prereq_rows: List[Prerequisite] = Prerequisite.query.filter_by(
        degree_plan_id=plan.id
    ).all()

    prereqs: Dict[str, List[str]] = {c.code: [] for c in course_rows}

    for row in prereq_rows:
        course_code = code_by_id.get(row.course_id)
        prereq_code = code_by_id.get(row.prereq_course_id)
        if course_code is None or prereq_code is None:
            # Either FK points to a course in a different plan or missing – skip
            continue
        prereqs[course_code].append(prereq_code)

    return {
        "courses": courses,
        "prereqs": prereqs,
        "allowed_semesters": allowed_semesters,
        "credits": credits,
        "max_credits_per_semester": max_credits_per_semester,
    }


# --------------------------------------------------------
# DEMO 1: only "each course once" + simple objective
# --------------------------------------------------------


def demo1():
    print("=== only 'each course once' + simple objective ===")

    courses = ["CS101", "CS102", "CS103"]
    allowed_semesters = {
        "CS101": [1, 2],
        "CS102": [1, 2, 3],
        "CS103": [2, 3],
    }

    # credits + prereqs don't matter yet, but we still pass them
    credits = {"CS101": 3, "CS102": 3, "CS103": 3}
    prereqs: Dict[str, List[str]] = {}
    max_credits = {1: 100, 2: 100, 3: 100}

    model, x = build_model(
        courses,
        prereqs,
        allowed_semesters,
        credits,
        max_credits,
        use_credit_limits=False,
        use_prereqs=False,
        minimize_last_semester=False,
    )

    model.solve(PULP_CBC_CMD(msg=False))
    status = LpStatus[model.status]
    print("Status:", status)

    for c in courses:
        chosen = None
        for s in allowed_semesters[c]:
            val = x[c][s].value()
            if val is not None and val > 0.5:
                chosen = s
                break
        print(f"  {c} -> semester {chosen}")


# --------------------------------------------------------
# DEMO 2: add CREDIT LIMITS
# --------------------------------------------------------


def demo2():
    print("=== add CREDIT LIMITS ===")

    courses = ["CS101", "CS102", "CS103", "CS201"]
    allowed_semesters = {
        "CS101": [1, 2],
        "CS102": [1, 2, 3],
        "CS103": [2, 3],
        "CS201": [2, 3],
    }

    credits = {
        "CS101": 3,
        "CS102": 3,
        "CS103": 3,
        "CS201": 3,
    }

    max_credits = {
        1: 6,
        2: 6,
        3: 6,
    }

    prereqs: Dict[str, List[str]] = {}

    model, x = build_model(
        courses,
        prereqs,
        allowed_semesters,
        credits,
        max_credits,
        use_credit_limits=True,
        use_prereqs=False,
        minimize_last_semester=False,
    )

    model.solve(PULP_CBC_CMD(msg=False))
    status = LpStatus[model.status]
    print("Status:", status)

    for c in courses:
        chosen = None
        for s in allowed_semesters[c]:
            val = x[c][s].value()
            if val is not None and val > 0.5:
                chosen = s
                break
        print(f"  {c} -> semester {chosen}")


# --------------------------------------------------------
# DEMO 3: CREDIT LIMITS + PREREQS + min last semester
# --------------------------------------------------------


def demo3():
    print("=== CREDIT LIMITS + PREREQS + minimize last semester ===")

    courses = ["CS101", "CS102", "CS103", "CS201"]
    allowed_semesters = {
        "CS101": [1, 2],
        "CS102": [1, 2, 3],
        "CS103": [2, 3],
        "CS201": [2, 3],
    }

    credits = {
        "CS101": 3,
        "CS102": 3,
        "CS103": 3,
        "CS201": 3,
    }

    prereqs = {
        "CS102": ["CS101"],
        "CS103": ["CS102"],
        "CS201": ["CS101"],
    }

    max_credits = {
        1: 6,
        2: 6,
        3: 6,
    }

    model, x = build_model(
        courses,
        prereqs,
        allowed_semesters,
        credits,
        max_credits,
        use_credit_limits=True,
        use_prereqs=True,
        minimize_last_semester=True,
    )

    model.solve(PULP_CBC_CMD(msg=False))
    status = LpStatus[model.status]
    print("Status:", status)

    for c in courses:
        chosen = None
        for s in allowed_semesters[c]:
            val = x[c][s].value()
            if val is not None and val > 0.5:
                chosen = s
                break
        print(f"  {c} -> semester {chosen}")


# --------------------------------------------------------
# Choose which step to run by default
# --------------------------------------------------------

if __name__ == "__main__":
    # demo1()
    # demo2()
    demo3()
