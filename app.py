from flask import Flask, render_template
from config import Config
from extensions import db, login_manager

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # init extentions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login" # we'll use later for @login_required

    # importing models after extintions are initalized 
    from models.user import User

    #Home route
    @app.route("/")
    def home():
        return render_template("home.html")
    
    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)