from extensions import db

# global default constraints per semester 
# we can change accordingly later, as in if we want specific constraints for a semester

class PlanConstraint(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    degree_plan_id = db.Column(
        db.Integer,
        db.ForeignKey("degree_plan.id"),
        nullable=False,
        unique=True, 
    )

    # per semester constraints, simple and global 
    min_credits_per_semester = db.Column(db.Integer, nullable=True)
    max_credits_per_semester = db.Column(db.Integer, nullable=True)
    max_courses_per_semester = db.Column(db.Integer, nullable=True)
    max_difficulty_per_semester = db.Column(db.Integer, nullable=True)

    total_semesters = db.Column(db.Integer, nullable=True)

    # solver behavior flags (3)
    enforce_prereqs = db.Column(db.Boolean, nullable=False, default=True)
    enforce_credit_limits = db.Column(db.Boolean, nullable=False, default=True)
    minimize_last_semester = db.Column(db.Boolean, nullable=False, default=True)
    
    degree_plan = db.relationship(
        "DegreePlan",
        backref=db.backref("constraints", uselist=False),
        lazy=True,
    )

    def __repr__(self):
        return f"<PlanConstraint plan={self.degree_plan_id}>"

