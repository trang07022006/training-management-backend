import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from werkzeug.security import generate_password_hash

from flask import Flask
from flask_jwt_extended import JWTManager

from app.models.login_session import LoginSession
from app.models.user import User
from app.services.auth_service import (
    AuthValidationError,
    authenticate_and_login,
    verify_password,
)


class AuthServiceTests(unittest.TestCase):
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

        self.user = User(
            id="user-456",
            email="trainer@example.com",
            password_hash=generate_password_hash("ValidPass123!"),
            role="trainer",
            status="active",
        )

        now = datetime.now(timezone.utc)
        self.session = LoginSession(
            session_id="session-456",
            user_id="user-456",
            refresh_jti="jti-456",
            created_at=now,
            last_activity_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=8),
        )
        self.tokens = {
            "access_token": "acc-token",
            "refresh_token": "ref-token",
        }

    def test_verify_password(self):
        hashed = generate_password_hash("MySecret123")
        self.assertTrue(verify_password(hashed, "MySecret123"))
        self.assertFalse(verify_password(hashed, "WrongSecret"))
        self.assertFalse(verify_password(hashed, ""))
        self.assertFalse(verify_password("", "MySecret123"))

    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_authenticate_and_login_success(self, mock_get_user, mock_create_session):
        mock_get_user.return_value = self.user
        mock_create_session.return_value = (self.session, self.tokens)

        with self.app.app_context():
            user, session, tokens = authenticate_and_login("trainer@example.com", "ValidPass123!")

        self.assertEqual(user.id, "user-456")
        self.assertEqual(session.session_id, "session-456")
        self.assertEqual(tokens["access_token"], "acc-token")
        mock_get_user.assert_called_once_with("trainer@example.com")
        mock_create_session.assert_called_once_with(user_id="user-456")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_authenticate_user_not_found(self, mock_get_user):
        mock_get_user.return_value = None

        with self.assertRaises(AuthValidationError) as ctx:
            authenticate_and_login("notfound@example.com", "ValidPass123!")

        self.assertEqual(ctx.exception.code, "INVALID_CREDENTIALS")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_authenticate_wrong_password(self, mock_get_user):
        mock_get_user.return_value = self.user

        with self.assertRaises(AuthValidationError) as ctx:
            authenticate_and_login("trainer@example.com", "IncorrectPass!")

        self.assertEqual(ctx.exception.code, "INVALID_CREDENTIALS")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_authenticate_disabled_account(self, mock_get_user):
        disabled_user = User(
            id="user-789",
            email="disabled@example.com",
            password_hash=generate_password_hash("ValidPass123!"),
            role="trainee",
            status="inactive",
        )
        mock_get_user.return_value = disabled_user

        with self.assertRaises(AuthValidationError) as ctx:
            authenticate_and_login("disabled@example.com", "ValidPass123!")

        self.assertEqual(ctx.exception.code, "ACCOUNT_DISABLED")

    def test_authenticate_empty_inputs(self):
        with self.assertRaises(AuthValidationError) as ctx:
            authenticate_and_login("", "ValidPass123!")
        self.assertEqual(ctx.exception.code, "EMAIL_REQUIRED")

        with self.assertRaises(AuthValidationError) as ctx:
            authenticate_and_login("trainer@example.com", "")
        self.assertEqual(ctx.exception.code, "PASSWORD_REQUIRED")


if __name__ == "__main__":
    unittest.main()
