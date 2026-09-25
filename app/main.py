from flask import Flask, jsonify
from flask_cors import CORS
from database.connection import get_db_connection

app = Flask(__name__)
CORS(app)


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
