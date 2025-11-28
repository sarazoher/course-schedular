from app import app, db 
from models.user import User

with app.app_context():
    db.create_all()
    print("DB CREATEDDDD")

  #  u = User(email="test@example.com", password_hash="1234")
  #  db.session.add(u)
  #  db.session.commit()
  #  print("Test user added tooo")

