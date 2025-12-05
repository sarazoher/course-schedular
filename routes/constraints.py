from flask import (
    Blueprint,
    render_template,
    redirect, url_for,
    request,
    flash,
    abort,
)
from flask_login import login_required, current_user

from extensions import db
from models.degree_plan import DegreePlan
from models.plan_constraint import PlanConstraint


constraints_bp = Blueprint("constraints", __name__)


@constraints_bp.route("/plans/<int:plan_id>/constraints", methods=["GET", "POST"])
@login_required
def edit_constraints(plan_id):
    plan = DegreePlan.query.filter_by(id=plan_id, user_id=current_user.id).first()
    if not plan:
        abort(404)

    pc = PlanConstraint.query.filter_by(degree_plan_id=plan.id).first()
    if not pc:
        pc = PlanConstraint(degree_plan_id=plan.id, total_semesters=6)
        db.session.add(pc)
        db.session.commit()

    if request.method == "POST":
        pc.total_semesters = int(request.form.get("total_semesters", pc.total_semesters))

        #Optional: max credits per semester
        max_per_sem = request.form.get("max_credits_per_semester")
        pc.max_credits_per_semester = int(max_per_sem) if max_per_sem else None

        db.session.commit()
        flash("Plan constraints updated.", "success")
        return redirect(url_for("main.view_plan", plan_id=plan.id))

    return render_template(
        "edit_constraints.html",
        plan=plan,
        pc=pc,
    )
