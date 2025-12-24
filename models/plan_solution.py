from datetime import datetime
from extensions import db


class PlanSolution(db.Model):
    __tablename__ = "plan_solution"

    id = db.Column(db.Integer, primary_key=True)

    plan_id = db.Column(
        db.Integer,
        db.ForeignKey("degree_plan.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Solver outcome summary
    status = db.Column(db.String(32), nullable=False)  # for example: "optimal", "infeasible", "not_solved", "error"
    objective_value = db.Column(db.Float, nullable=True)

    # Stored payloads (JSON serialized as text)
    solution_json = db.Column(db.Text, nullable=True)   # schedule + assignments
    warnings_json = db.Column(db.Text, nullable=True)   # unresolved prereqs, ignored externals...
    meta_json = db.Column(db.Text, nullable=True)       # optional: solver version, runtime...

    # Relationships
    plan = db.relationship(
        "DegreePlan",
        backref=db.backref("solutions", cascade="all, delete-orphan", lazy="dynamic"),
    )

    def __repr__(self) -> str:
        return f"<PlanSolution plan={self.plan_id} status={self.status} at={self.created_at}>"
