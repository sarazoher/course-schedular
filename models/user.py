"""User model and Flask-Login integration."""

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db, login_manager

class User(UserMixin, db.Model):
    """Database model for a registered user."""

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password: str) -> None:
        """Hash and store the given plain-text password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Return True if the given password matches the stored hash."""
        return check_password_hash(self.password_hash, password)


    def __repr__(self):
        return f"<User {self.email}"
    

#tell Flask-Login how to load a user 

@login_manager.user_loader
def load_user(user_id):
    """Tell Flask-Login how to load a user from the stored ID."""
    return User.query.get(int(user_id))