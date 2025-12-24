from datetime import datetime
from extensions import db


class DegreePlan(db.Model):
    __tablename__ = "degree_plan"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # User relationship (many plans per user)
    user = db.relationship("User", back_populates="degree_plans", lazy=True)

    # Children: cascade so a plan delete cleans everything
    courses = db.relationship(
        "Course",
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy=True,
    )

    prerequisites = db.relationship(
        "Prerequisite",
        back_populates="degree_plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy=True,
    )

    constraints = db.relationship(
        "PlanConstraint",
        back_populates="degree_plan",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy=True,
    )

    def __repr__(self) -> str:
        return f"<DegreePlan {self.name}>"
