from flask import render_template, redirect, url_for, request, abort, flash
from flask_login import login_required, current_user

from pulp import LpStatus, PULP_CBC_CMD

from . import main_bp
from models.degree_plan import DegreePlan
from models.plan_constraint import PlanConstraint
from services.solver import build_inputs_from_plan, build_model
from extensions import db
from utils.semesters import format_semester_label


def _analyze_infeasibility_hints(inputs: dict) -> list[str]:
    """Best-effort hints for common infeasibility causes.
    This does not prove infeasibility, it's just meant to point the user
    toward likely fixes (offerings, prereqs, credit limits...)
    """
    hints: list[str] = []

    courses = inputs.get("courses", [])
    prereqs = inputs.get("prereqs", {})
    allowed = inputs.get("allowed_semesters", {})
    credits = inputs.get("credits", {})
    max_credits = inputs.get("max_credits_per_semester", {})

    # Any course with no allowed semester
    no_allowed = [c for c in courses if not allowed.get(c)]
    if no_allowed:
        hints.append(
            "Some courses have no allowed semesters (no offerings selected). "
            f"Fix offerings for: {', '.join(no_allowed)}."
        )

    # 2) Offering-vs-prereq contradictions (brute check: is there *any* sp < sc?)
    impossible_edges: list[tuple[str, str]] = []
    for c, pres in prereqs.items():
        for p in pres:
            ap = allowed.get(p, [])
            ac = allowed.get(c, [])
            if ap and ac:
                if not any(sp < sc for sp in ap for sc in ac):
                    impossible_edges.append((p, c))
    if impossible_edges:
        pairs = "; ".join([f"{p} → {c}" for (p, c) in impossible_edges[:6]])
        more = "" if len(impossible_edges) <= 6 else f" (+{len(impossible_edges) - 6} more)"
        hints.append(
            "Some prerequisites are impossible given the current offerings/allowed semesters: "
            f"{pairs}{more}."
        )

    # 3) Credit capacity check (quick necessary condition)
    total_credits = sum(int(credits.get(c, 0) or 0) for c in courses)
    total_capacity = sum(int(v or 0) for v in max_credits.values())

    if max_credits and total_capacity and total_credits > total_capacity:
        hints.append(
            "Your total course credits exceed the plan's total credit capacity across semesters. "
            "Increase 'max credits per semester' or increase 'total semesters'."
        )

    # 4) Cycle check in prerequisite graph
    # Only consider nodes that exist in the plan
    graph = {c: set(prereqs.get(c, [])) for c in courses}
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for pre in graph.get(node, set()):
            if pre in graph:  # ignore prereqs that are not in the plan
                if dfs(pre):
                    return True
        visiting.remove(node)
        visited.add(node)
        return False

    has_cycle = any(dfs(c) for c in courses)
    if has_cycle:
        hints.append(
            "There is a prerequisite cycle (A requires B requires ... requires A). "
            "Break the cycle in the prerequisites tab."
        )

    return hints

@main_bp.route("/plans/<int:plan_id>/solve", methods=["POST"])
@login_required
def solve_plan(plan_id: int):
    """
    User-facing route:
    - checks the plan belongs to the current user
    - builds solver inputs from the DB
    - runs the MILP solver
    - renders a semester-by-semester schedule
    """
    # ensure the plan exists and belongs to the current user
    plan = DegreePlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first()
    if plan is None:
        abort(404)

    # Build inputs from DB
    try:
        inputs = build_inputs_from_plan(plan.id)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    # Pull plan settings (needed for semesters_per_year labels + solver flags later)
    pc = PlanConstraint.query.filter_by(degree_plan_id=plan.id).first()

    # Compute hints (only used if solver can't produce a valid schedule)
    infeasible_hints = _analyze_infeasibility_hints(inputs)

    # Build and solve the model
    model, x = build_model(
        inputs["courses"],
        inputs["prereqs"],
        inputs["allowed_semesters"],
        inputs["credits"],
        inputs["max_credits_per_semester"],
        use_credit_limits=True,
        use_prereqs=True,
        minimize_last_semester=True,
    )

    model.solve(PULP_CBC_CMD(msg=0))
    status = LpStatus[model.status]

    # Semesters list used by BOTH optimal and non-optimal renders
    semesters = sorted(inputs["max_credits_per_semester"].keys())

    # Semester labels for UI (Year/Term when semesters_per_year is set)
    semesters_per_year = None
    if pc and pc.semesters_per_year:
        semesters_per_year = pc.semesters_per_year

    semester_labels = {
        s: format_semester_label(s, semesters_per_year)
        for s in semesters
    }

    # If solver did not find an optimal schedule, do NOT render assignments
    if status != "Optimal":
        if not infeasible_hints:
            infeasible_hints = [
                "No feasible schedule exists under the current constraints. "
                "Check offerings, prerequisites, credit limits, and total semesters."
            ]
        return render_template(
            "plan_schedule.html",
            plan=plan,
            status=status,
            semesters=semesters,
            semester_labels=semester_labels,
            courses_by_semester={s: [] for s in semesters},
            infeasible_hints=infeasible_hints,
        )

    # Map course_code → Course row
    course_by_code = {c.code: c for c in plan.courses}

    # Extract chosen semester per course
    assignments = []
    for c in inputs["courses"]:
        chosen_semester = None
        for s in inputs["allowed_semesters"][c]:
            var = x[c][s]
            if var.varValue is not None and var.varValue > 0.5:
                chosen_semester = s
                break

        course_obj = course_by_code.get(c)
        assignments.append(
            {
                "code": c,
                "name": course_obj.name if course_obj else c,
                "credits": inputs["credits"][c],
                "difficulty": getattr(course_obj, "difficulty", None),
                "semester": chosen_semester,
            }
        )

    # Group by semester for easier templating
    courses_by_semester = {s: [] for s in semesters}
    for a in assignments:
        if a["semester"] is not None:
            courses_by_semester[a["semester"]].append(a)

    return render_template(
        "plan_schedule.html",
        plan=plan,
        status=status,
        semesters=semesters,
        semester_labels=semester_labels,
        courses_by_semester=courses_by_semester,
        infeasible_hints=[],
    )
