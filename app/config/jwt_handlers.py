from flask import jsonify


def register_jwt_handlers(jwt):
    @jwt.expired_token_loader
    def handle_expired_token(jwt_header, jwt_payload):
        if jwt_payload.get("type") == "access":
            code = "ACCESS_TOKEN_EXPIRED"
        else:
            code = "SESSION_EXPIRED"

        return jsonify({"code": code}), 401

    @jwt.unauthorized_loader
    def handle_missing_token(reason):
        return jsonify({"code": "AUTH_REQUIRED"}), 401

    @jwt.invalid_token_loader
    def handle_invalid_token(reason):
        return jsonify({"code": "TOKEN_INVALID"}), 422