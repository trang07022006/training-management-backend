import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError

from app.routes.session_routes import session_bp
from app.services.session_service import create_login_session


class LogoutRoutesTests(unittest.TestCase):
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

        with self.app.app_context():
            self.session, self.tokens = create_login_session("test-user")

        # Chạy route và service thật; chỉ giả lập repository.
        patcher = patch(
            "app.services.session_service.session_repository"
        )
        self.repository = patcher.start()
        self.addCleanup(patcher.stop)

        self.repository.get_session_by_id.return_value = self.session

    def post_logout(self, token=None):
        if token is None:
            token = self.tokens["access_token"]

        return self.client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_logout_success(self):
        response = self.post_logout()

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.data, b"")

        self.repository.get_session_by_id.assert_called_once_with(
            self.session.session_id
        )
        self.repository.revoke_session.assert_called_once_with(
            session_id=self.session.session_id,
            user_id="test-user",
        )

    def test_repeated_logout_succeeds_without_revoking_again(self):
        first_response = self.post_logout()
        self.assertEqual(first_response.status_code, 204)

        # Mô phỏng lần đọc tiếp theo thấy phiên đã bị thu hồi.
        self.repository.get_session_by_id.return_value = replace(
            self.session,
            revoked_at=datetime.now(timezone.utc),
        )

        second_response = self.post_logout()

        self.assertEqual(second_response.status_code, 204)
        self.repository.revoke_session.assert_called_once_with(
            session_id=self.session.session_id,
            user_id="test-user",
        )

    def test_reject_missing_token(self):
        response = self.client.post("/api/auth/logout")

        self.assertEqual(response.status_code, 401)
        self.repository.get_session_by_id.assert_not_called()
        self.repository.revoke_session.assert_not_called()

    def test_reject_refresh_token(self):
        response = self.post_logout(self.tokens["refresh_token"])

        self.assertEqual(response.status_code, 422)
        self.repository.get_session_by_id.assert_not_called()
        self.repository.revoke_session.assert_not_called()

    def test_reject_token_without_session_id(self):
        with self.app.app_context():
            token = create_access_token(identity="test-user")

        response = self.post_logout(token)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json(),
            {"code": "SESSION_INVALID"},
        )
        self.repository.get_session_by_id.assert_not_called()
        self.repository.revoke_session.assert_not_called()

    def test_reject_unknown_session(self):
        self.repository.get_session_by_id.return_value = None

        response = self.post_logout()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json(),
            {"code": "SESSION_INVALID"},
        )
        self.repository.revoke_session.assert_not_called()

    def test_reject_session_owned_by_another_user(self):
        self.repository.get_session_by_id.return_value = replace(
            self.session,
            user_id="another-user",
        )

        response = self.post_logout()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json(),
            {"code": "SESSION_INVALID"},
        )
        self.repository.revoke_session.assert_not_called()

    def test_allow_logout_of_expired_database_session(self):
        # Access token vẫn còn hạn, nhưng phiên trong DB đã hết hạn idle.
        self.repository.get_session_by_id.return_value = replace(
            self.session,
            idle_expires_at=(
                datetime.now(timezone.utc) - timedelta(seconds=1)
            ),
        )

        response = self.post_logout()

        self.assertEqual(response.status_code, 204)
        self.repository.revoke_session.assert_called_once_with(
            session_id=self.session.session_id,
            user_id="test-user",
        )

    def test_database_errors_return_503_without_details(self):
        for operation in ("get_session_by_id", "revoke_session"):
            with self.subTest(operation=operation):
                self.repository.reset_mock(side_effect=True)
                self.repository.get_session_by_id.return_value = (
                    self.session
                )
                getattr(self.repository, operation).side_effect = (
                    MySQLError("private database connection details")
                )

                response = self.post_logout()

                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.get_json(),
                    {"code": "SESSION_STORAGE_UNAVAILABLE"},
                )


if __name__ == "__main__":
    unittest.main()