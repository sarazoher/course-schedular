from datetime import datetime
from extensions import db


class DegreePlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # User relationship (many plans per user)
    user = db.relationship("User", backref="degree_plans", lazy=True) 

    def __repr__(self):
        return f"<DgreePlan {self.name}>"
