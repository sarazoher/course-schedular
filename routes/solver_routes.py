# routes/solver_routes.py

from flask import render_template, redirect, url_for, request, abort, flash
from flask_login import login_required, current_user

from pulp import LpStatus, PULP_CBC_CMD

from . import main_bp
from models.degree_plan import DegreePlan
from models.plan_constraint import PlanConstraint
from services.solver import build_inputs_from_plan, build_model
from extensions import db
from utils.semesters import format_semester_label
from services.validation import validate_inputs_before_solve


@main_bp.route("/plans/<int:plan_id>/solve", methods=["GET", "POST"])
@login_required
def solve_plan(plan_id: int):
    """
    User-facing route:
    - checks the plan belongs to the current user
    - builds solver inputs from the DB
    - runs the MILP solver
    - renders a semester-by-semester schedule
    """
    # Safety: this endpoint is intended to be triggered from a POST button.
    # If a user hits it via GET (typing the URL for example), redirect them back.
    if request.method == "GET":
        flash("Use the 'Solve' button to run the solver.", "info")
        return redirect(url_for("main.view_plan", plan_id=plan_id))

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
        # This is where "No courses defined for plan_id=..." will land
        flash(str(e), "error")
        return redirect(url_for("main.view_plan", plan_id=plan_id))
    
    # Pre-solve Validation
    precheck_hints = validate_inputs_before_solve(inputs)
    if precheck_hints:
        return render_template(
            "plan_schedule.html",
            plan=plan,
            status="Infeasible",
            semesters=[],
            semester_labels={},
            courses_by_semester={},
            infeasible_hints=precheck_hints,
        )
    
    # print("COURSES:", inputs["courses"])
    # print("ALLOWED:", inputs["allowed_semesters"])


    # Solver flags come from PlanConstraint (Plan settings)
    pc = PlanConstraint.query.filter_by(degree_plan_id=plan.id).first()
    # default behavior if settings row is missing
    use_prereqs = True if pc is None else bool(pc.enforce_prereqs)
    use_credit_limits = True if pc is None else bool(pc.enforce_credit_limits)
    minimize_last_semester = True if pc is None else bool(pc.minimize_last_semester)

    # Build and solve the model
    model, x = build_model(
        inputs["courses"],
        inputs["prereqs"],
        inputs["allowed_semesters"],
        inputs["credits"],
        inputs["max_credits_per_semester"],
        use_credit_limits=use_credit_limits,
        use_prereqs=use_prereqs,
        minimize_last_semester=minimize_last_semester,
    )

    model.solve(PULP_CBC_CMD(msg=0))
    status = LpStatus[model.status]
    prereqs = inputs.get("prereqs", {})
    allowed = inputs.get("allowed_semesters", {})

    infeasible_hints = []

    if status != "Optimal":

        # (A) Missing offerings: course has no allowed semesters
        no_offerings = [c for c in inputs.get("courses", []) if not allowed.get(c)]
        if no_offerings:
            infeasible_hints.append(
                "Some courses have no offerings (no allowed semesters): "
                + ", ".join(no_offerings[:6])
                + (", ..." if len(no_offerings) > 6 else "")
            )

    # (B) Credit capacity pressure: total credits > total capacity
    max_by_sem = inputs.get("max_credits_per_semester", {}) or {}
    credits = inputs.get("credits", {}) or {}

    semesters_for_capacity = sorted(max_by_sem.keys())
    total_capacity = sum(int(v) for v in max_by_sem.values()) if max_by_sem else 0

    total_credits = 0
    missing_credit = []
    for c in inputs.get("courses", []):
        if c not in credits:
            missing_credit.append(c)
        else:
            total_credits += int(credits[c])

    if missing_credit:
        infeasible_hints.append(
            "Some courses are missing credit values: "
            + ", ".join(missing_credit[:6])
            + (", ..." if len(missing_credit) > 6 else "")
        )

    if total_capacity and total_credits > total_capacity:
        infeasible_hints.append(
            f"Total credits ({total_credits}) exceed schedule capacity "
            f"({len(semesters_for_capacity)} semesters, total max {total_capacity} credits). "
            "Increase total semesters / max credits, or reduce course credits."
        )

    # Impossible prereq edges (offerings make prereq ordering impossible)
    impossible_edges = []
    for course, pres in prereqs.items():
        for pre in pres:
            pre_max = max(allowed.get(pre, []), default=None)
            course_min = min(allowed.get(course, []), default=None)
            if pre_max is not None and course_min is not None and pre_max >= course_min:
                impossible_edges.append(f"{pre} → {course}")

    if impossible_edges:
        infeasible_hints.append(
            "Some prerequisites are impossible due to offerings: the prerequisite can’t be scheduled "
            "before the course in any allowed semester. Conflicts: "
            + ", ".join(impossible_edges[:6])
            + (", ..." if len(impossible_edges) > 6 else "")
            + ". Fix by adjusting Offerings (allowed semesters) or Prerequisites."
        )

    # Cycle hint
    graph = {}
    for course, pres in prereqs.items():
        for pre in pres:
            graph.setdefault(pre, []).append(course)

    visited = set()
    on_stack = set()

    def dfs(node):
        visited.add(node)
        on_stack.add(node)
        for nxt in graph.get(node, []):
            if nxt not in visited:
                if dfs(nxt):
                    return True
            elif nxt in on_stack:
                return True
        on_stack.remove(node)
        return False

    has_cycle = any(dfs(n) for n in list(graph.keys()) if n not in visited)
    if has_cycle:
        infeasible_hints.append(
            "There is a prerequisite cycle (A requires B requires ... requires A). "
            "Break the cycle in the prerequisites tab."
        )

                
    semesters = sorted(inputs["max_credits_per_semester"].keys())
    semesters_per_year = pc.semesters_per_year if pc and pc.semesters_per_year else None
    semester_labels = {s: format_semester_label(s, semesters_per_year) for s in semesters}

    courses_by_semester = {s: [] for s in semesters}

    if status == "Optimal":
        # Setup: Map course_code → Course row
        course_by_code = {c.code: c for c in plan.courses}

        # Extract chosen semester per course
        for c in inputs["courses"]:
            chosen_semester = None
            for s in inputs["allowed_semesters"][c]:
                var = x[c][s]
                if var.varValue is not None and var.varValue > 0.5:
                    chosen_semester = s
                    break
            
            if chosen_semester is None:
                continue

            course_obj = course_by_code.get(c)

            # KeyError
            courses_by_semester.setdefault(chosen_semester, []).append(
                {
                    "code": c,
                    "name": course_obj.name if course_obj else c,
                    "credits": inputs["credits"][c],
                    "difficulty": getattr(course_obj, "difficulty", None),
                }
            )
        
        # Trim empty semesters 
        used = [s for s, lst in courses_by_semester.items() if lst]
        if used:
            last_used = max(used)
            semesters = [s for s in semesters if s <= last_used]
            courses_by_semester = {s: courses_by_semester.get(s, []) for s in semesters}
            semester_labels = {s: semester_labels.get(s, f"Semester {s}") for s in semesters}

    #print("STATUS:", status)
    #print("SEMESTERS:", semesters)
    #print("COURSES_BY_SEMESTER:", courses_by_semester)


    return render_template(
        "plan_schedule.html",
        plan=plan,
        status=status,
        semesters=semesters,
        semester_labels=semester_labels,
        courses_by_semester=courses_by_semester,
        infeasible_hints=infeasible_hints,
    )
