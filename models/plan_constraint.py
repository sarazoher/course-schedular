from extensions import db


# Global default constraints per plan (not per semester)
class PlanConstraint(db.Model):
    __tablename__ = "plan_constraint"

    id = db.Column(db.Integer, primary_key=True)

    degree_plan_id = db.Column(
        db.Integer,
        db.ForeignKey("degree_plan.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # 1-to-1 with DegreePlan
    )

    # per semester constraints (global defaults)
    min_credits_per_semester = db.Column(db.Integer, nullable=True)
    max_credits_per_semester = db.Column(db.Integer, nullable=True)
    max_courses_per_semester = db.Column(db.Integer, nullable=True)
    max_difficulty_per_semester = db.Column(db.Integer, nullable=True)

    # plan structure
    total_semesters = db.Column(db.Integer, nullable=True)
    years = db.Column(db.Integer, nullable=True)
    semesters_per_year = db.Column(db.Integer, nullable=True)

    # solver behavior flags
    enforce_prereqs = db.Column(db.Boolean, nullable=False, default=True)
    enforce_credit_limits = db.Column(db.Boolean, nullable=False, default=True)
    minimize_last_semester = db.Column(db.Boolean, nullable=False, default=True)

    degree_plan = db.relationship("DegreePlan", back_populates="constraints", lazy=True)

    def __repr__(self) -> str:
        return f"<PlanConstraint plan={self.degree_plan_id}>"
