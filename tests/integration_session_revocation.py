import secrets
import unittest
from datetime import timedelta

from flask import Flask
from flask_jwt_extended import JWTManager

from app.database.connection import get_db_connection
from app.repositories.session_repository import (
    get_session_by_id,
    update_session_activity,
)
from app.routes.session_routes import session_bp
from app.services.session_service import (
    create_stored_login_session,
    logout_stored_session,
    renew_login_session,
)
from app.utils.session_auth import session_required


def build_test_app(secret_key):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        JWT_SECRET_KEY=secret_key,
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(hours=8),
        SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
    )
    JWTManager(app)
    app.register_blueprint(session_bp)

    @app.get("/test/protected")
    @session_required
    def protected():
        return {"ok": True}

    return app


class SessionRevocationMySQLTests(unittest.TestCase):
    def setUp(self):
        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT DATABASE()")
                database_name = cursor.fetchone()[0]

            if database_name != "training_management":
                raise RuntimeError("Database khác dự kiến. Dừng kiểm thử.")
        finally:
            connection.close()

        self.secret_key = secrets.token_hex(32)
        self.app = build_test_app(self.secret_key)

        with self.app.app_context():
            self.session, self.tokens = create_stored_login_session(
                "scrum39-integration-test"
            )

        # Dọn phiên kể cả khi một phép kiểm tra bị lỗi.
        self.addCleanup(self.cleanup_session)

    def cleanup_session(self):
        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM auth_sessions
                    WHERE session_id = %s AND user_id = %s
                    """,
                    (self.session.session_id, self.session.user_id),
                )
            connection.commit()
        finally:
            connection.close()

        self.assertIsNone(get_session_by_id(self.session.session_id))

    def auth_header(self, token_name):
        return {
            "Authorization": f"Bearer {self.tokens[token_name]}"
        }

    def test_new_app_still_rejects_revoked_session(self):
        client = self.app.test_client()

        response = client.get(
            "/test/protected",
            headers=self.auth_header("access_token"),
        )
        self.assertEqual(response.status_code, 200)

        response = client.post(
            "/api/auth/logout",
            headers=self.auth_header("access_token"),
        )
        self.assertEqual(response.status_code, 204)

        # Tạo một ứng dụng mới, giữ nguyên khóa JWT và database.
        new_app = build_test_app(self.secret_key)
        new_client = new_app.test_client()

        response = new_client.get(
            "/test/protected",
            headers=self.auth_header("access_token"),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json()["code"],
            "SESSION_REVOKED",
        )

        response = new_client.post(
            "/api/auth/refresh",
            headers=self.auth_header("refresh_token"),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json()["code"],
            "SESSION_REVOKED",
        )

    def test_stale_renewal_cannot_update_revoked_session(self):
        # Mô phỏng yêu cầu gia hạn đã đọc phiên trước khi logout.
        original = get_session_by_id(self.session.session_id)
        self.assertIsNotNone(original)

        with self.app.app_context():
            candidate = renew_login_session(
                original,
                now=original.created_at + timedelta(minutes=1),
            )

        # Logout xảy ra trước khi yêu cầu gia hạn ghi xuống MySQL.
        logout_stored_session(
            session_id=original.session_id,
            user_id=original.user_id,
        )

        before = get_session_by_id(original.session_id)
        self.assertIsNotNone(before)
        self.assertIsNotNone(before.revoked_at)

        updated = update_session_activity(original, candidate)

        self.assertFalse(updated)

        after = get_session_by_id(original.session_id)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()