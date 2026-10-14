from flask import Flask, jsonify
from flask_cors import CORS
from app.config.avatar_config import configure_avatar
from app.config.jwt_handlers import register_jwt_handlers
from app.config.jwt_config import configure_jwt
from app.database.connection import get_db_connection
from app.extensions import jwt
from app.routes.auth_routes import auth_bp
from app.routes.session_routes import session_bp
from app.routes.program_subject_routes import program_subject_bp
from app.routes.subject_routes import subject_bp
from app.routes.training_program_routes import training_program_bp
from app.routes.user_routes import user_bp
from app.routes.user_role_routes import user_role_bp
from app.routes.public_consultation_routes import public_consultation_bp
from app.routes.subject_session_routes import subject_session_bp
from app.routes.lead_routes import lead_bp
from app.routes.student_routes import student_bp
from app.routes.class_routes import class_bp
from app.routes.enrollment_routes import enrollment_bp
from app.routes.holiday_routes import holiday_bp
from app.routes.schedule_routes import schedule_bp


app = Flask(__name__)

configure_jwt(app)
configure_avatar(app)
jwt.init_app(app)
register_jwt_handlers(jwt)

CORS(app)

app.register_blueprint(auth_bp)
app.register_blueprint(session_bp)
app.register_blueprint(subject_bp)
app.register_blueprint(subject_session_bp)
app.register_blueprint(training_program_bp)
app.register_blueprint(program_subject_bp)
app.register_blueprint(user_bp)
app.register_blueprint(user_role_bp)
app.register_blueprint(public_consultation_bp)
app.register_blueprint(lead_bp)
app.register_blueprint(student_bp)
app.register_blueprint(class_bp)
app.register_blueprint(enrollment_bp)
app.register_blueprint(holiday_bp)
app.register_blueprint(schedule_bp)

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "message": "Training Management System API is running"
    })


@app.route("/api/health/database", methods=["GET"])
def database_health():
    try:
        connection = get_db_connection()
        connection.close()

        return jsonify({
            "status": "ok",
            "message": "MySQL connection successful"
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


if __name__ == "__main__":
    app.run(
        debug=True,
        host="0.0.0.0",
        port=5000
    )
