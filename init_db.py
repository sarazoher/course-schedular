from app import app
from extensions import db
from models.user import User
from models.degree_plan import DegreePlan
from models.course import Course


with app.app_context():
    print("DB URI:", app.config["SQLALCHEMY_DATABASE_URI"])
    db.create_all()
    print("DB CREATEDDDD")

  #  u = User(email="test@example.com", password_hash="1234")
  #  db.session.add(u)
  #  db.session.commit()
  #  print("Test user added tooo")

