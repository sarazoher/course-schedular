from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db

class User(UserMixin, db.Model):

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password: str) -> None:
        # use PBKDF2 instead of the default scrypt
        self.password_hash = generate_password_hash(
            password,
            method="pbkdf2:sha256",
            salt_length=16,
        )
    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


    def __repr__(self):
        return f"<User {self.email}>"
    

