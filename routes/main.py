from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from extensions import db
from models.degree_plan import DegreePlan

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    # uses existing templates/home.html
    return render_template("home.html")


@main_bp.route("/dashboard")
@login_required
def dashboard():
    # Fetch plans for the logged-in user
    plans = DegreePlan.query.filter_by(user_id=current_user.id).all()
    return render_template("dashboard.html", degree_plans=plans)


@main_bp.route("/plans/new", methods=["GET", "POST"])
@login_required
def create_plan():
    if request.method == "POST":
        name = request.form.get("name")

        if not name:
            flash("Plan name is required.")
            return redirect(url_for("main.create_plan"))

        plan = DegreePlan(user_id=current_user.id, name=name)
        db.session.add(plan)
        db.session.commit()

        flash("Degree plan created.")
        return redirect(url_for("main.dashboard"))

    return render_template("create_plan.html")

