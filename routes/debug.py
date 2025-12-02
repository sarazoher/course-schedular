from flask import Blueprint, jsonify, abort
from pulp import PULP_CBC_CMD, LpStatus

from models.degree_plan import DegreePlan
from services.solver import build_model, build_inputs_from_plan

debug_bp = Blueprint("debug", __name__)


@debug_bp.route("/test-solve/<int:plan_id>")
def test_solve(plan_id: int):
    # HTTP concern → we *can* use get_or_404 here if you want:
    plan = DegreePlan.query.get(plan_id)
    if plan is None:
        abort(404, description=f"DegreePlan {plan_id} not found")

    try:
        inputs = build_inputs_from_plan(plan_id)
    except ValueError as e:
        # build_inputs_from_plan raised something like "no courses", etc.
        abort(400, description=str(e))

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

    status_code = model.solve(PULP_CBC_CMD(msg=1))
    status = LpStatus[model.status]

    assignments = []
    for c in inputs["courses"]:
        for s in inputs["allowed_semesters"][c]:
            var = x[c][s]
            if var.varValue is not None and var.varValue > 0.5:
                assignments.append(
                    {
                        "course_code": c,
                        "semester": s,
                        "credits": inputs["credits"][c],
                    }
                )

    return jsonify(
        {
            "plan_id": plan_id,
            "status_code": int(model.status),
            "status": status,
            "assignments": assignments,
        }
    )
