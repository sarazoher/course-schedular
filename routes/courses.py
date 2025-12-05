from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    abort,
    flash,
)
from flask_login import login_required, current_user

from extensions import db
from models.degree_plan import DegreePlan
from models.course import Course

courses_bp = Blueprint("courses", __name__)

# Edit Course
@courses_bp.route("/plans/<int:plan_id>/courses/<int:course_id>/edit", methods=["GET", "POST"])
@login_required
def edit_course(plan_id, course_id):
    plan = DegreePlan.query.filter_by(id=plan_id, user_id=current_user.id,).first()
    if not plan:
        abort(404)

    course = Course.query.filter_by(
        id=course_id,
        user_id=current_user.id,  
    ).first()
    if not course:
        abort(404)

    if request.method == "POST":
        course.code = request.form.get("code", "").strip()
        course.name = request.form.get("name", "").strip()
        course.credits = int(request.form.get("credits", 0))
        course.difficulty = int(request.form.get("difficulty", 0)) or None

        db.session.commit()
        flash("Course updated.", "success")
        return redirect(url_for("main.view_plan", plan_id=plan.id))
    
    return render_template("edit_course.html", plan=plan, course=course)

# Delete Course
@courses_bp.route("/plans/<int:plan_id>/courses/<int:course_id>/delete", methods=["POST"])
@login_required
def delete_course(plan_id, course_id):
    plan = DegreePlan.query.filter_by(id=plan_id, user_id=current_user.id,).first()
    if not plan:
        abort(404)

    course = Course.query.filter_by(id=course_id, degree_plan_id=plan.id,).first()
    if not course:
        abort(404)

    db.session.delete(course)
    db.session.commit()

    flash("Course deleted.", "success")
    return redirect(url_for("main.view_plan", plan_id=plan.id))
