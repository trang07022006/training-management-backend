"""
Test kiểm tra phân biệt rõ ràng giữa 3 trạng thái tài khoản khi đăng nhập:
1. active: cho phép đăng nhập bình thường
2. inactive: từ chối với mã lỗi ACCOUNT_INACTIVE, thông báo "Tài khoản hiện không hoạt động. Vui lòng liên hệ quản trị viên."
3. locked: từ chối với mã lỗi ACCOUNT_LOCKED, thông báo khóa tài khoản
4. inactive không bị đổi thành locked sau khi đăng nhập thất bại
5. locked giữ nguyên behavior SCRUM-27/SCRUM-108
6. Sai mật khẩu với active user -> trả INVALID_CREDENTIALS
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from werkzeug.security import generate_password_hash

from app.main import app
from app.models.login_session import LoginSession
from app.models.user import User
from app.services.auth_service import (
    AuthValidationError,
    authenticate_and_login,
    validate_credentials,
)


class TestDistinguishInactiveAndLockedLogin(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

        self.password = "ValidPassword123!"
        self.password_hash = generate_password_hash(self.password)
        self.now = datetime.now(timezone.utc)

        self.active_user = User(
            id="u-active",
            email="active@daotao.edu.vn",
            password_hash=self.password_hash,
            name="Active User",
            role="trainee",
            status="active",
        )

        self.inactive_user = User(
            id="u-inactive",
            email="inactive@daotao.edu.vn",
            password_hash=self.password_hash,
            name="Inactive User",
            role="trainee",
            status="inactive",
        )

        self.locked_user = User(
            id="u-locked",
            email="locked@daotao.edu.vn",
            password_hash=self.password_hash,
            name="Locked User",
            role="trainee",
            status="locked",
        )

    def tearDown(self):
        self.ctx.pop()

    # 1. active + đúng mật khẩu -> login PASS
    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_01_active_user_correct_password_passes(self, mock_get_user, mock_create_sess):
        from app.services.token_service import create_login_tokens

        mock_get_user.return_value = self.active_user
        mock_session = LoginSession(
            session_id="sess-active",
            user_id="u-active",
            refresh_jti="jti-active",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )
        with self.app.app_context():
            mock_tokens = create_login_tokens("u-active", "sess-active")
        mock_create_sess.return_value = (mock_session, mock_tokens)

        resp = self.client.post("/api/auth/login", json={
            "email": "active@daotao.edu.vn",
            "password": self.password,
        })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["id"], "u-active")
        self.assertEqual(data["user"]["role"], "trainee")

    # 2. inactive + đúng mật khẩu -> 403, ACCOUNT_INACTIVE, "Tài khoản hiện không hoạt động. Vui lòng liên hệ quản trị viên."
    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_02_inactive_user_correct_password_returns_account_inactive(self, mock_get_user, mock_create_sess):
        mock_get_user.return_value = self.inactive_user

        resp = self.client.post("/api/auth/login", json={
            "email": "inactive@daotao.edu.vn",
            "password": self.password,
        })

        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertEqual(data["code"], "ACCOUNT_INACTIVE")
        self.assertEqual(data["message"], "Tài khoản hiện không hoạt động. Vui lòng liên hệ quản trị viên.")
        self.assertNotIn("access_token", data)
        mock_create_sess.assert_not_called()

    # 3. locked + đúng mật khẩu -> 403, ACCOUNT_LOCKED, thông báo khóa
    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_03_locked_user_correct_password_returns_account_locked(self, mock_get_user, mock_create_sess):
        mock_get_user.return_value = self.locked_user

        resp = self.client.post("/api/auth/login", json={
            "email": "locked@daotao.edu.vn",
            "password": self.password,
        })

        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertEqual(data["code"], "ACCOUNT_LOCKED")
        self.assertIn("khóa", data["message"])
        self.assertNotIn("access_token", data)
        mock_create_sess.assert_not_called()

    # 4. inactive không bị đổi thành locked sau khi đăng nhập thất bại
    @patch("app.services.auth_service.user_repository.update_user_status")
    @patch("app.services.auth_service.user_repository.update_user_lockout")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_04_inactive_user_does_not_mutate_status_on_failure(
        self, mock_get_user, mock_update_lockout, mock_update_status
    ):
        mock_get_user.return_value = self.inactive_user

        # Thử đăng nhập sai mật khẩu
        resp = self.client.post("/api/auth/login", json={
            "email": "inactive@daotao.edu.vn",
            "password": "WrongPassword999!",
        })
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(self.inactive_user.status, "inactive")
        # Không bao giờ gọi update_user_status làm đổi trạng thái
        mock_update_status.assert_not_called()

    # 5. locked vẫn giữ behavior SCRUM-27 / SCRUM-108
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_05_locked_user_wrong_password_anti_enumeration(self, mock_get_user):
        """Tài khoản locked + sai mật khẩu -> 401 INVALID_CREDENTIALS (anti-enumeration)."""
        mock_get_user.return_value = self.locked_user

        resp = self.client.post("/api/auth/login", json={
            "email": "locked@daotao.edu.vn",
            "password": "WrongPassword999!",
        })
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertEqual(data["code"], "INVALID_CREDENTIALS")
        self.assertEqual(data["message"], "Email hoặc mật khẩu không đúng")

    # 6. sai mật khẩu với active user -> vẫn dùng thông báo đăng nhập sai hiện tại
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_06_active_user_wrong_password_returns_invalid_credentials(self, mock_get_user):
        mock_get_user.return_value = self.active_user

        resp = self.client.post("/api/auth/login", json={
            "email": "active@daotao.edu.vn",
            "password": "WrongPassword999!",
        })
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertEqual(data["code"], "INVALID_CREDENTIALS")
        self.assertEqual(data["message"], "Email hoặc mật khẩu không đúng")


if __name__ == "__main__":
    unittest.main()
