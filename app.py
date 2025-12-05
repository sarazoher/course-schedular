from flask import Flask
from config import Config
from extensions import db, login_manager

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # init extentions
    db.init_app(app)
    login_manager.init_app(app)

    # import and register blueprints
    from auth.routes import auth_bp
    from routes.main import main_bp
    from routes.courses import courses_bp
    from routes.offerings import offerings_bp
    from routes.prereqs import prereqs_bp
    from routes.constraints import constraints_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(offerings_bp)
    app.register_blueprint(prereqs_bp)
    app.register_blueprint(constraints_bp)

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)