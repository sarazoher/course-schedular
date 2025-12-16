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

    infeasible_hints = []

    if status != "Optimal":
        prereqs = inputs.get("prereqs", {})
        allowed = inputs.get("allowed_semesters", {})

        impossible_edges = []
        for course, pres in prereqs.items():
            for pre in pres:
                pre_max = max(allowed.get(pre, []), default=None)
                course_min = min(allowed.get(course, []), default=None)
                if pre_max is not None and course_min is not None and pre_max >= course_min:
                    impossible_edges.append(f"{pre} → {course}")

        if impossible_edges:
            infeasible_hints.append(
                "Some prerequisites are impossible given the current offerings/allowed semesters: "
                + ", ".join(impossible_edges[:6])
                + (", ..." if len(impossible_edges) > 6 else "")
            )
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
                "There in a prerequisite cycle (A requires B requires ... requires A). "
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
