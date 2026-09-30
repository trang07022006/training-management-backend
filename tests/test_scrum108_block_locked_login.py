import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager
from werkzeug.security import generate_password_hash

from app.models.login_session import LoginSession
from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.services.auth_service import AuthValidationError, validate_credentials


class Scrum108BlockLockedLoginTests(unittest.TestCase):
    """
    Kiểm thử SCRUM-108: Chặn đăng nhập khi tài khoản bị khóa.
    1. Active user + đúng password -> Thành công (200, cấp token và session)
    2. Locked user + đúng password -> Bị từ chối 403 ACCOUNT_LOCKED
    3. Locked user + sai password -> Không rò rỉ trạng thái khóa, trả 401 INVALID_CREDENTIALS (anti-enumeration)
    4. Active user + sai password -> Trả 401 INVALID_CREDENTIALS
    5. Tuyệt đối không phát hành token khi tài khoản bị khóa
    6. Tuyệt đối không tạo phiên làm việc (session) khi tài khoản bị khóa
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum108-api-at-least-32-chars",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(auth_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.plain_pass = "SecurePass123!"
        self.password_hash = generate_password_hash(self.plain_pass)

        self.active_user = User(
            id="user-active-108",
            email="active@daotao.edu.vn",
            password_hash=self.password_hash,
            name="Active User 108",
            role="trainee",
            status="active",
        )

        self.locked_user = User(
            id="user-locked-108",
            email="locked@daotao.edu.vn",
            password_hash=self.password_hash,
            name="Locked User 108",
            role="trainee",
            status="locked",
        )

    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_01_active_user_correct_password_login_success(self, mock_get_user, mock_create_sess):
        """1. Tài khoản active + đúng mật khẩu -> Đăng nhập thành công, nhận token và session."""
        mock_get_user.return_value = self.active_user
        fake_session = LoginSession(
            session_id="sess-active-108",
            user_id="user-active-108",
            refresh_jti="ref-jti",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )
        with self.app.app_context():
            from flask_jwt_extended import create_access_token, create_refresh_token
            mock_create_sess.return_value = (fake_session, {
                "access_token": create_access_token("user-active-108"),
                "refresh_token": create_refresh_token("user-active-108"),
            })

            resp = self.client.post("/api/auth/login", json={
                "email": "active@daotao.edu.vn",
                "password": self.plain_pass,
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("access_token", data)
        self.assertIn("session_id", data)

    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_02_locked_user_correct_password_login_denied(self, mock_get_user, mock_create_sess):
        """2. Tài khoản locked + đúng mật khẩu -> Bị từ chối 403 ACCOUNT_LOCKED, không tạo session."""
        mock_get_user.return_value = self.locked_user

        resp = self.client.post("/api/auth/login", json={
            "email": "locked@daotao.edu.vn",
            "password": self.plain_pass,
        })

        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertEqual(data["code"], "ACCOUNT_LOCKED")
        self.assertIn("khóa", data["message"])
        self.assertNotIn("access_token", data)
        # Khẳng định không bao giờ gọi hàm tạo session
        mock_create_sess.assert_not_called()

    @patch("app.services.auth_service.user_repository.update_user_lockout")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_03_locked_user_wrong_password_anti_enumeration(self, mock_get_user, mock_update_lockout):
        """3. Tài khoản locked + sai mật khẩu -> Trả 401 INVALID_CREDENTIALS, không lộ trạng thái khóa."""
        mock_get_user.return_value = self.locked_user

        resp = self.client.post("/api/auth/login", json={
            "email": "locked@daotao.edu.vn",
            "password": "WrongPassword999!",
        })

        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertEqual(data["code"], "INVALID_CREDENTIALS")
        self.assertEqual(data["message"], "Email hoặc mật khẩu không đúng")

    @patch("app.services.auth_service.user_repository.update_user_lockout")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_04_active_user_wrong_password_behavior(self, mock_get_user, mock_update_lockout):
        """4. Tài khoản active + sai mật khẩu -> Trả 401 INVALID_CREDENTIALS."""
        mock_get_user.return_value = self.active_user

        resp = self.client.post("/api/auth/login", json={
            "email": "active@daotao.edu.vn",
            "password": "WrongPassword999!",
        })

        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertEqual(data["code"], "INVALID_CREDENTIALS")

    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_05_no_token_no_session_when_locked(self, mock_get_user, mock_create_sess):
        """5 & 6. Kiểm tra trực tiếp tại validate_credentials: ném ngoại lệ trước khi tạo session."""
        mock_get_user.return_value = self.locked_user

        with self.assertRaises(AuthValidationError) as ctx:
            validate_credentials("locked@daotao.edu.vn", self.plain_pass)

        self.assertEqual(ctx.exception.code, "ACCOUNT_LOCKED")
        mock_create_sess.assert_not_called()


if __name__ == "__main__":
    unittest.main()
