import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from werkzeug.security import generate_password_hash

from app.main import app
from app.models.user import User
from app.services.auth_service import (
    ACCOUNT_INACTIVE_MESSAGE,
    ACCOUNT_LOCKED_MESSAGE,
    ACCOUNT_TEMP_LOCKED_MESSAGE,
    INVALID_CREDENTIALS_MESSAGE,
    validate_credentials,
)


class TestLoginAccountRestrictions(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

        self.password = "ValidPass123!"
        self.password_hash = generate_password_hash(self.password)
        self.now = datetime.now(timezone.utc)

        self.active_user = User(
            id="u-active-1",
            email="active@daotao.edu.vn",
            password_hash=self.password_hash,
            name="Active User",
            role="trainee",
            status="active",
        )

        self.inactive_user = User(
            id="u-inactive-1",
            email="inactive@daotao.edu.vn",
            password_hash=self.password_hash,
            name="Inactive User",
            role="trainee",
            status="inactive",
        )

        self.locked_user = User(
            id="u-locked-1",
            email="locked@daotao.edu.vn",
            password_hash=self.password_hash,
            name="Locked User",
            role="trainee",
            status="locked",
        )

    def tearDown(self):
        self.ctx.pop()

    # 1. Active user + correct password -> PASS (200)
    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_01_active_user_correct_password_pass(self, mock_get_user, mock_create_sess):
        mock_get_user.return_value = self.active_user
        mock_session = MagicMock()
        mock_session.session_id = "sess-1"
        mock_session.idle_expires_at = self.now + timedelta(minutes=15)
        mock_session.absolute_expires_at = self.now + timedelta(hours=8)
        from flask_jwt_extended import create_access_token, create_refresh_token
        acc = create_access_token(identity="u-active-1", additional_claims={"sid": "sess-1"})
        ref = create_refresh_token(identity="u-active-1", additional_claims={"sid": "sess-1"})
        mock_create_sess.return_value = (mock_session, {"access_token": acc, "refresh_token": ref})

        resp = self.client.post("/api/auth/login", json={
            "email": "active@daotao.edu.vn",
            "password": self.password,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["email"], "active@daotao.edu.vn")

    # 2. Active user + wrong password under threshold -> 401 INVALID_CREDENTIALS
    @patch("app.services.auth_service.user_repository.update_user_lockout")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_02_wrong_password_under_threshold_returns_401(self, mock_get_user, mock_update_lockout):
        self.active_user.failed_login_attempts = 2
        mock_get_user.return_value = self.active_user

        resp = self.client.post("/api/auth/login", json={
            "email": "active@daotao.edu.vn",
            "password": "WrongPassword!",
        })
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertEqual(data["code"], "INVALID_CREDENTIALS")
        self.assertEqual(data["message"], INVALID_CREDENTIALS_MESSAGE)
        mock_update_lockout.assert_called_with(
            user_id=self.active_user.id,
            failed_login_attempts=3,
            locked_until=None,
        )

    # 3. Exceeding threshold (attempt 5) -> 403 ACCOUNT_TEMP_LOCKED
    @patch("app.services.auth_service.user_repository.update_user_lockout")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_03_exceeding_threshold_triggers_account_temp_locked(self, mock_get_user, mock_update_lockout):
        self.active_user.failed_login_attempts = 4
        self.active_user.locked_until = None
        mock_get_user.return_value = self.active_user

        resp = self.client.post("/api/auth/login", json={
            "email": "active@daotao.edu.vn",
            "password": "WrongPassword!",
        })
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertEqual(data["code"], "ACCOUNT_TEMP_LOCKED")
        self.assertEqual(data["message"], ACCOUNT_TEMP_LOCKED_MESSAGE)
        self.assertIn("locked_until", data)
        self.assertIn("retry_after_seconds", data)
        self.assertGreater(data["retry_after_seconds"], 0)

    # 4. During temporary lock -> rejected even with correct password
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_04_during_temp_lock_rejected(self, mock_get_user):
        self.active_user.failed_login_attempts = 5
        self.active_user.locked_until = self.now + timedelta(minutes=14)
        mock_get_user.return_value = self.active_user

        resp = self.client.post("/api/auth/login", json={
            "email": "active@daotao.edu.vn",
            "password": self.password,
        })
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertEqual(data["code"], "ACCOUNT_TEMP_LOCKED")
        self.assertIn("locked_until", data)
        self.assertIn("retry_after_seconds", data)

    # 5. Countdown expires -> login allowed again
    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.reset_user_lockout")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_05_login_allowed_after_temp_lock_expires(self, mock_get_user, mock_reset_lockout, mock_create_sess):
        self.active_user.failed_login_attempts = 5
        self.active_user.locked_until = self.now - timedelta(seconds=1)
        mock_get_user.return_value = self.active_user

        mock_session = MagicMock()
        mock_session.session_id = "sess-2"
        mock_session.idle_expires_at = self.now + timedelta(minutes=15)
        mock_session.absolute_expires_at = self.now + timedelta(hours=8)
        from flask_jwt_extended import create_access_token, create_refresh_token
        acc = create_access_token(identity="u-active-1", additional_claims={"sid": "sess-2"})
        ref = create_refresh_token(identity="u-active-1", additional_claims={"sid": "sess-2"})
        mock_create_sess.return_value = (mock_session, {"access_token": acc, "refresh_token": ref})

        resp = self.client.post("/api/auth/login", json={
            "email": "active@daotao.edu.vn",
            "password": self.password,
        })
        self.assertEqual(resp.status_code, 200)
        mock_reset_lockout.assert_called_with(user_id=self.active_user.id)

    # 6. Inactive account -> 403 ACCOUNT_INACTIVE
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_06_inactive_account_rejected(self, mock_get_user):
        mock_get_user.return_value = self.inactive_user

        resp = self.client.post("/api/auth/login", json={
            "email": "inactive@daotao.edu.vn",
            "password": self.password,
        })
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertEqual(data["code"], "ACCOUNT_INACTIVE")
        self.assertEqual(data["message"], ACCOUNT_INACTIVE_MESSAGE)

    # 7. Locked account (admin lock) -> 403 ACCOUNT_LOCKED
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_07_locked_account_rejected(self, mock_get_user):
        mock_get_user.return_value = self.locked_user

        resp = self.client.post("/api/auth/login", json={
            "email": "locked@daotao.edu.vn",
            "password": self.password,
        })
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertEqual(data["code"], "ACCOUNT_LOCKED")
        self.assertEqual(data["message"], ACCOUNT_LOCKED_MESSAGE)


if __name__ == "__main__":
    unittest.main()
