import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import JWTManager, decode_token
from mysql.connector import Error as MySQLError

from app.routes.session_routes import session_bp
from app.services.session_service import (
    SessionValidationError,
    create_login_session,
)


class SessionRoutesTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-only-key-not-for-production-123456789",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            JWT_REFRESH_TOKEN_EXPIRES=timedelta(hours=8),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )

        JWTManager(self.app)
        self.app.register_blueprint(session_bp)
        self.client = self.app.test_client()

        # Tạo JWT thật để kiểm tra cả lớp xác thực của API.
        with self.app.app_context():
            self.session, self.tokens = create_login_session("test-user")

        # Chỉ giả lập thao tác gia hạn phiên trong database.
        patcher = patch(
            "app.routes.session_routes.renew_stored_session"
        )
        self.mock_renew = patcher.start()
        self.addCleanup(patcher.stop)

        self.mock_renew.return_value = self.session

    def post_refresh(self, token=None):
        if token is None:
            token = self.tokens["refresh_token"]

        return self.client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_refresh_success_and_caps_access_expiry(self):
        # Phiên chỉ còn 2 phút, dù access token cấu hình là 15 phút.
        deadline = datetime.now(timezone.utc) + timedelta(minutes=2)
        self.mock_renew.return_value = replace(
            self.session,
            idle_expires_at=deadline,
            absolute_expires_at=deadline,
        )

        response = self.post_refresh()

        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        with self.app.app_context():
            access = decode_token(data["access_token"])

        self.assertEqual(access["type"], "access")
        self.assertEqual(access["sub"], "test-user")
        self.assertEqual(access["sid"], self.session.session_id)
        self.assertEqual(access["exp"], int(deadline.timestamp()))
        self.assertEqual(data["access_expires_at"], access["exp"])
        self.assertEqual(data["token_type"], "Bearer")
        self.assertNotIn("refresh_token", data)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

        self.mock_renew.assert_called_once_with(
            session_id=self.session.session_id,
            user_id="test-user",
            refresh_jti=self.session.refresh_jti,
        )

    def test_reject_missing_token(self):
        response = self.client.post("/api/auth/refresh")

        self.assertEqual(response.status_code, 401)
        self.mock_renew.assert_not_called()

    def test_reject_access_token_used_as_refresh(self):
        response = self.post_refresh(self.tokens["access_token"])

        self.assertEqual(response.status_code, 422)
        self.mock_renew.assert_not_called()

    def test_reject_malformed_token(self):
        response = self.post_refresh("not-a-valid-jwt")

        self.assertEqual(response.status_code, 422)
        self.mock_renew.assert_not_called()

    def test_reject_revoked_session(self):
        self.mock_renew.side_effect = SessionValidationError(
            "SESSION_REVOKED"
        )

        response = self.post_refresh()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json()["code"],
            "SESSION_REVOKED",
        )
        self.assertNotIn("access_token", response.get_json())

    def test_reject_expired_session(self):
        self.mock_renew.side_effect = SessionValidationError(
            "SESSION_EXPIRED"
        )

        response = self.post_refresh()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json()["code"],
            "SESSION_EXPIRED",
        )
        self.assertNotIn("access_token", response.get_json())

    def test_return_conflict_for_concurrent_update(self):
        self.mock_renew.side_effect = SessionValidationError(
            "SESSION_UPDATE_CONFLICT"
        )

        response = self.post_refresh()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["code"],
            "SESSION_UPDATE_CONFLICT",
        )

    def test_database_error_does_not_expose_details(self):
        self.mock_renew.side_effect = MySQLError(
            "private database connection details"
        )

        response = self.post_refresh()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {"code": "SESSION_STORAGE_UNAVAILABLE"},
        )
        self.assertNotIn(
            "private database connection details",
            response.get_data(as_text=True),
        )


if __name__ == "__main__":
    unittest.main()