from flask import Flask, jsonify
from flask_cors import CORS
from app.config.jwt_handlers import register_jwt_handlers
from app.config.jwt_config import configure_jwt
from app.database.connection import get_db_connection
from app.extensions import jwt
from app.routes.auth_routes import auth_bp
from app.routes.session_routes import session_bp


app = Flask(__name__)

configure_jwt(app)
jwt.init_app(app)
register_jwt_handlers(jwt)

CORS(app)

app.register_blueprint(session_bp)
app.register_blueprint(auth_bp)


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
