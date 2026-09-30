import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from werkzeug.security import generate_password_hash

from flask import Flask
from flask_jwt_extended import JWTManager, decode_token
from mysql.connector import Error as MySQLError

from app.models.login_session import LoginSession
from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.services.auth_service import AuthValidationError


class AuthRoutesTests(unittest.TestCase):
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
        self.app.register_blueprint(auth_bp)
        self.client = self.app.test_client()

        self.user = User(
            id="user-123",
            email="trainee@example.com",
            password_hash=generate_password_hash("SecretPassword123!"),
            role="trainee",
            status="active",
        )

        now = datetime.now(timezone.utc)
        self.session = LoginSession(
            session_id="test-session-id",
            user_id="user-123",
            refresh_jti="test-jti",
            created_at=now,
            last_activity_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=8),
        )

        # Mock database update/reset lockout để không kết nối MySQL thật trong route tests
        self.patch_update_lockout = patch("app.services.auth_service.user_repository.update_user_lockout")
        self.patch_reset_lockout = patch("app.services.auth_service.user_repository.reset_user_lockout")
        self.mock_update_lockout = self.patch_update_lockout.start()
        self.mock_reset_lockout = self.patch_reset_lockout.start()
        self.addCleanup(self.patch_update_lockout.stop)
        self.addCleanup(self.patch_reset_lockout.stop)


    def post_login(self, data=None, content_type="application/json"):
        if data is None:
            data = {
                "email": "trainee@example.com",
                "password": "SecretPassword123!",
            }

        return self.client.post(
            "/api/auth/login",
            json=data if content_type == "application/json" else None,
            data=data if content_type != "application/json" else None,
            content_type=content_type,
        )

    @patch("app.routes.auth_routes.authenticate_and_login")
    def test_login_success(self, mock_auth):
        with self.app.app_context():
            from app.services.token_service import create_login_tokens
            real_tokens = create_login_tokens(self.user.id, self.session.session_id)

        mock_auth.return_value = (self.user, self.session, real_tokens)

        response = self.post_login()

        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
        self.assertEqual(data["token_type"], "Bearer")
        self.assertEqual(data["user"]["id"], "user-123")
        self.assertEqual(data["user"]["email"], "trainee@example.com")
        self.assertEqual(data["user"]["role"], "trainee")
        self.assertEqual(data["session_id"], "test-session-id")
        self.assertIn("idle_expires_at", data)
        self.assertIn("absolute_expires_at", data)
        self.assertIn("access_expires_at", data)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

        with self.app.app_context():
            access_payload = decode_token(data["access_token"])
            refresh_payload = decode_token(data["refresh_token"])

        self.assertEqual(access_payload["type"], "access")
        self.assertEqual(access_payload["sub"], "user-123")
        self.assertEqual(access_payload["sid"], "test-session-id")
        self.assertEqual(refresh_payload["type"], "refresh")
        self.assertEqual(refresh_payload["sub"], "user-123")
        self.assertEqual(refresh_payload["sid"], "test-session-id")

        mock_auth.assert_called_once_with(
            email="trainee@example.com",
            password="SecretPassword123!",
        )

    def test_reject_non_json_body(self):
        response = self.client.post(
            "/api/auth/login",
            data="not-json",
            content_type="text/plain",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "INVALID_REQUEST")

    def test_reject_missing_email(self):
        response = self.post_login(data={"password": "SecretPassword123!"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "EMAIL_REQUIRED")

    def test_reject_empty_email(self):
        response = self.post_login(data={"email": "   ", "password": "SecretPassword123!"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "EMAIL_REQUIRED")

    def test_reject_missing_password(self):
        response = self.post_login(data={"email": "trainee@example.com"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "PASSWORD_REQUIRED")

    def test_reject_empty_password(self):
        response = self.post_login(data={"email": "trainee@example.com", "password": ""})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "PASSWORD_REQUIRED")

    @patch("app.routes.auth_routes.authenticate_and_login")
    def test_reject_invalid_credentials(self, mock_auth):
        mock_auth.side_effect = AuthValidationError("INVALID_CREDENTIALS")

        response = self.post_login()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["code"], "INVALID_CREDENTIALS")
        self.assertEqual(response.get_json()["message"], "Email hoặc mật khẩu không đúng")

    @patch("app.routes.auth_routes.authenticate_and_login")
    def test_reject_disabled_account(self, mock_auth):
        mock_auth.side_effect = AuthValidationError("ACCOUNT_DISABLED")

        response = self.post_login()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "ACCOUNT_DISABLED")

    @patch("app.routes.auth_routes.authenticate_and_login")
    def test_database_error_returns_503_without_leak(self, mock_auth):
        mock_auth.side_effect = MySQLError("sensitive db connection info")

        response = self.post_login()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "SESSION_STORAGE_UNAVAILABLE")
        self.assertNotIn("sensitive db connection info", response.get_data(as_text=True))

    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_login_route_credentials_success(self, mock_get_user, mock_create_session):
        mock_get_user.return_value = self.user
        with self.app.app_context():
            from app.services.token_service import create_login_tokens
            tokens = create_login_tokens(self.user.id, self.session.session_id)
        mock_create_session.return_value = (self.session, tokens)

        response = self.post_login(data={"email": "trainee@example.com", "password": "SecretPassword123!"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["email"], "trainee@example.com")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_login_route_email_not_found(self, mock_get_user):
        mock_get_user.return_value = None

        response = self.post_login(data={"email": "notfound@example.com", "password": "SecretPassword123!"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["code"], "INVALID_CREDENTIALS")
        self.assertEqual(response.get_json()["message"], "Email hoặc mật khẩu không đúng")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_login_route_wrong_password(self, mock_get_user):
        mock_get_user.return_value = self.user

        response = self.post_login(data={"email": "trainee@example.com", "password": "IncorrectPassword123!"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["code"], "INVALID_CREDENTIALS")
        self.assertEqual(response.get_json()["message"], "Email hoặc mật khẩu không đúng")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_login_route_invalid_credentials_returns_same_status_and_message(self, mock_get_user):
        """Xác nhận cả 2 trường hợp (email không tồn tại và password sai) trả cùng status và message."""
        # 1. Email không tồn tại
        mock_get_user.return_value = None
        res_email_not_found = self.post_login(
            data={"email": "notfound@example.com", "password": "SecretPassword123!"}
        )

        # 2. Password sai
        mock_get_user.return_value = self.user
        res_wrong_password = self.post_login(
            data={"email": "trainee@example.com", "password": "WrongPassword123!"}
        )

        # Cùng status HTTP 401
        self.assertEqual(res_email_not_found.status_code, 401)
        self.assertEqual(res_wrong_password.status_code, 401)
        self.assertEqual(res_email_not_found.status_code, res_wrong_password.status_code)

        data_email_not_found = res_email_not_found.get_json()
        data_wrong_password = res_wrong_password.get_json()

        # Cùng body và cùng thông báo "Email hoặc mật khẩu không đúng"
        self.assertEqual(data_email_not_found["code"], "INVALID_CREDENTIALS")
        self.assertEqual(data_wrong_password["code"], "INVALID_CREDENTIALS")
        self.assertEqual(data_email_not_found["message"], "Email hoặc mật khẩu không đúng")
        self.assertEqual(data_wrong_password["message"], "Email hoặc mật khẩu không đúng")
        self.assertEqual(data_email_not_found, data_wrong_password)

        # Không chứa các thông điệp làm lộ thông tin tài khoản
        for body in (data_email_not_found, data_wrong_password):
            msg = body["message"].lower()
            self.assertNotIn("user not found", msg)
            self.assertNotIn("email does not exist", msg)
            self.assertNotIn("password incorrect", msg)

    # =========================================================================
    # SCRUM-34 Route Tests: Khóa tạm 15 phút sau 5 lần đăng nhập sai
    # =========================================================================

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_login_route_locked_account_rejected_with_403(self, mock_get_user):
        """Tài khoản đang bị khóa -> route trả về 403 ACCOUNT_LOCKED."""
        now = datetime.now(timezone.utc)
        self.user.locked_until = now + timedelta(minutes=10)
        self.user.failed_login_attempts = 5
        mock_get_user.return_value = self.user

        response = self.post_login(data={"email": "trainee@example.com", "password": "SecretPassword123!"})
        self.assertEqual(response.status_code, 403)
        data = response.get_json()
        self.assertEqual(data["code"], "ACCOUNT_LOCKED")
        self.assertIn("khóa", data["message"].lower())
        self.assertIn("locked_until", data)

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_login_route_locks_account_on_fifth_failed_attempt(self, mock_get_user):
        """Sai lần thứ 5 -> route trả về 403 ACCOUNT_LOCKED và có thời gian khóa."""
        self.user.failed_login_attempts = 4
        self.user.locked_until = None
        mock_get_user.return_value = self.user

        response = self.post_login(data={"email": "trainee@example.com", "password": "WrongPassword!"})
        self.assertEqual(response.status_code, 403)
        data = response.get_json()
        self.assertEqual(data["code"], "ACCOUNT_LOCKED")
        self.assertIn("locked_until", data)
        self.assertEqual(self.user.failed_login_attempts, 5)
        self.assertIsNotNone(self.user.locked_until)

    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_login_route_allows_login_after_lockout_expires(self, mock_get_user, mock_create_session):
        """Hết 15 phút khóa -> route cho phép đăng nhập thành công khi nhập đúng mật khẩu."""
        now = datetime.now(timezone.utc)
        self.user.failed_login_attempts = 5
        self.user.locked_until = now - timedelta(minutes=1)
        mock_get_user.return_value = self.user

        with self.app.app_context():
            from app.services.token_service import create_login_tokens
            tokens = create_login_tokens(self.user.id, self.session.session_id)
        mock_create_session.return_value = (self.session, tokens)

        response = self.post_login(data={"email": "trainee@example.com", "password": "SecretPassword123!"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user.failed_login_attempts, 0)
        self.assertIsNone(self.user.locked_until)
        self.mock_reset_lockout.assert_called_once_with(user_id="user-123")

    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_login_route_resets_failed_attempts_on_success(self, mock_get_user, mock_create_session):
        """Đăng nhập thành công -> reset failed_login_attempts."""
        self.user.failed_login_attempts = 3
        self.user.locked_until = None
        mock_get_user.return_value = self.user

        with self.app.app_context():
            from app.services.token_service import create_login_tokens
            tokens = create_login_tokens(self.user.id, self.session.session_id)
        mock_create_session.return_value = (self.session, tokens)

        response = self.post_login(data={"email": "trainee@example.com", "password": "SecretPassword123!"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user.failed_login_attempts, 0)
        self.mock_reset_lockout.assert_called_once_with(user_id="user-123")


if __name__ == "__main__":
    unittest.main()



