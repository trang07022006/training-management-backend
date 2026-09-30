import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError

from app.services.session_service import create_login_session
from app.utils.session_auth import session_required


class SessionAuthTests(unittest.TestCase):
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

        # Theo dõi xem phần xử lý nghiệp vụ có được chạy không.
        self.business_handler = Mock(return_value={"ok": True})

        # Route này chỉ tồn tại trong test.
        @self.app.get("/test/protected")
        @session_required
        def protected():
            return self.business_handler()

        self.client = self.app.test_client()

        with self.app.app_context():
            self.session, self.tokens = create_login_session("test-user")

        patcher = patch("app.utils.session_auth.get_session_by_id")
        self.mock_get = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_get.return_value = self.session

    def request_protected(self, token=None):
        if token is None:
            token = self.tokens["access_token"]

        return self.client.get(
            "/test/protected",
            headers={"Authorization": f"Bearer {token}"},
        )

    def assert_session_denied(self, code):
        response = self.request_protected()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"code": code})
        self.business_handler.assert_not_called()

    def test_allow_valid_session(self):
        response = self.request_protected()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})
        self.mock_get.assert_called_once_with(self.session.session_id)
        self.business_handler.assert_called_once_with()

    def test_reject_missing_token(self):
        response = self.client.get("/test/protected")

        self.assertEqual(response.status_code, 401)
        self.mock_get.assert_not_called()
        self.business_handler.assert_not_called()

    def test_reject_refresh_token(self):
        response = self.request_protected(self.tokens["refresh_token"])

        self.assertEqual(response.status_code, 422)
        self.mock_get.assert_not_called()
        self.business_handler.assert_not_called()

    def test_reject_token_without_session_id(self):
        with self.app.app_context():
            token = create_access_token(identity="test-user")

        response = self.request_protected(token)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json(),
            {"code": "SESSION_INVALID"},
        )
        self.mock_get.assert_not_called()
        self.business_handler.assert_not_called()

    def test_reject_unknown_session(self):
        self.mock_get.return_value = None

        self.assert_session_denied("SESSION_INVALID")

    def test_reject_session_owned_by_another_user(self):
        self.mock_get.return_value = replace(
            self.session,
            user_id="another-user",
        )

        self.assert_session_denied("SESSION_INVALID")

    def test_reject_expired_session(self):
        past = datetime.now(timezone.utc) - timedelta(seconds=1)

        for field in ("idle_expires_at", "absolute_expires_at"):
            with self.subTest(expired_field=field):
                self.mock_get.return_value = replace(
                    self.session,
                    **{field: past},
                )

                self.assert_session_denied("SESSION_EXPIRED")

    def test_reject_revoked_session(self):
        self.mock_get.return_value = replace(
            self.session,
            revoked_at=datetime.now(timezone.utc),
        )

        self.assert_session_denied("SESSION_REVOKED")

    def test_database_error_blocks_business_handler(self):
        self.mock_get.side_effect = MySQLError(
            "private database details"
        )

        response = self.request_protected()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {"code": "SESSION_STORAGE_UNAVAILABLE"},
        )
        self.business_handler.assert_not_called()


if __name__ == "__main__":
    unittest.main()