from functools import wraps

from flask import g, jsonify
from flask_jwt_extended import (
    get_jwt,
    get_jwt_identity,
    verify_jwt_in_request,
)
from mysql.connector import Error as MySQLError

from app.repositories.session_repository import get_session_by_id
from app.services.session_service import (
    SessionValidationError,
    validate_login_session,
)


def session_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        # Kiểm tra chữ ký, hạn JWT và chỉ chấp nhận access token.
        verify_jwt_in_request(
            refresh=False,
            locations=["headers"],
        )

        session_id = get_jwt().get("sid")
        user_id = get_jwt_identity()

        if any(
            not isinstance(value, str) or not value.strip()
            for value in (session_id, user_id)
        ):
            return jsonify({"code": "SESSION_INVALID"}), 401

        try:
            session = get_session_by_id(session_id)

            if session is None or session.user_id != user_id:
                return jsonify({"code": "SESSION_INVALID"}), 401

            # Dùng lại logic kiểm tra hết hạn và thu hồi đã viết.
            validate_login_session(session)

        except SessionValidationError as error:
            return jsonify({"code": error.code}), 401
        except MySQLError:
            return jsonify({"code": "SESSION_STORAGE_UNAVAILABLE"}), 503

        # API có thể lấy phiên đã kiểm tra qua g.login_session.
        g.login_session = session

        return view(*args, **kwargs)

    return wrapped
    