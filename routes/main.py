from flask import Blueprint, render_template
from flask_login import login_required

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    # uses existing templates/home.html
    return render_template("home.html")


@main_bp.route("/dashboard")
@login_required
def dashboard():
    # later: fetch real degree plans for the logged-in user
    degree_plans = []
    return render_template("dashboard.html", degree_plans=degree_plans)
