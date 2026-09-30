"""
SCRUM-36: Kiểm thử tổng thể chức năng đăng nhập (Backend Verification).

Mục tiêu kiểm thử:
1. POST /api/auth/login.
2. Email + mật khẩu đúng -> đăng nhập thành công, trả token, user info (id, email, role) và session metadata.
3. Email không tồn tại -> trả 401 với thông báo: "Email hoặc mật khẩu không đúng".
4. Mật khẩu sai -> cùng mã lỗi và thông báo như trên.
5. Sai lần 1-4 -> tăng failed_login_attempts counter.
6. Sai lần thứ 5 -> khóa tạm 15 phút (HTTP 403, ACCOUNT_LOCKED).
7. Trong thời gian khóa -> từ chối đăng nhập với 403 ACCOUNT_LOCKED.
8. Hết thời gian khóa -> cho phép thử đăng nhập lại.
9. Đăng nhập thành công -> reset failed login counter và locked_until.
10. Token và session sử dụng cơ chế SCRUM-19 hiện có (JWT access, refresh, stored session).
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from werkzeug.security import generate_password_hash

from flask import Flask
from flask_jwt_extended import JWTManager, decode_token

from app.models.login_session import LoginSession
from app.models.user import User
from app.routes.auth_routes import auth_bp


class Scrum36OverallLoginTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-only-key-not-for-production-scrum-36",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            JWT_REFRESH_TOKEN_EXPIRES=timedelta(hours=8),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )

        JWTManager(self.app)
        self.app.register_blueprint(auth_bp)
        self.client = self.app.test_client()

        self.user = User(
            id="user-36",
            email="trainer.scrum36@daotao.edu.vn",
            password_hash=generate_password_hash("ValidPassword123!"),
            role="trainer",
            status="active",
            failed_login_attempts=0,
            locked_until=None,
        )

        now = datetime.now(timezone.utc)
        self.session = LoginSession(
            session_id="session-scrum36-id",
            user_id="user-36",
            refresh_jti="jti-scrum36",
            created_at=now,
            last_activity_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=8),
        )

        self.patch_update_lockout = patch("app.services.auth_service.user_repository.update_user_lockout")
        self.patch_reset_lockout = patch("app.services.auth_service.user_repository.reset_user_lockout")
        self.mock_update_lockout = self.patch_update_lockout.start()
        self.mock_reset_lockout = self.patch_reset_lockout.start()
        self.addCleanup(self.patch_update_lockout.stop)
        self.addCleanup(self.patch_reset_lockout.stop)

    def post_login(self, data):
        return self.client.post(
            "/api/auth/login",
            json=data,
            content_type="application/json",
        )

    # 1. & 2. Kiểm tra POST /api/auth/login & Email + mật khẩu đúng
    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_01_and_02_login_success_with_valid_credentials(self, mock_get_user, mock_create_session):
        mock_get_user.return_value = self.user

        with self.app.app_context():
            from app.services.token_service import create_login_tokens
            tokens = create_login_tokens(self.user.id, self.session.session_id)
        mock_create_session.return_value = (self.session, tokens)

        response = self.post_login({
            "email": "trainer.scrum36@daotao.edu.vn",
            "password": "ValidPassword123!",
        })

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
        self.assertEqual(data["token_type"], "Bearer")
        self.assertEqual(data["user"]["id"], "user-36")
        self.assertEqual(data["user"]["email"], "trainer.scrum36@daotao.edu.vn")
        self.assertEqual(data["user"]["role"], "trainer")
        self.assertEqual(data["session_id"], "session-scrum36-id")

    # 3. & 4. Email không tồn tại và Mật khẩu sai đều trả cùng thông báo "Email hoặc mật khẩu không đúng"
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_03_and_04_generic_error_message_for_both_nonexistent_email_and_wrong_password(self, mock_get_user):
        # Case 1: Email không tồn tại
        mock_get_user.return_value = None
        res_nonexistent = self.post_login({
            "email": "nonexistent@daotao.edu.vn",
            "password": "SomePassword123!",
        })

        # Case 2: Mật khẩu sai
        mock_get_user.return_value = self.user
        res_wrong_pw = self.post_login({
            "email": "trainer.scrum36@daotao.edu.vn",
            "password": "WrongPassword123!",
        })

        self.assertEqual(res_nonexistent.status_code, 401)
        self.assertEqual(res_wrong_pw.status_code, 401)

        body_nonexistent = res_nonexistent.get_json()
        body_wrong_pw = res_wrong_pw.get_json()

        self.assertEqual(body_nonexistent["code"], "INVALID_CREDENTIALS")
        self.assertEqual(body_wrong_pw["code"], "INVALID_CREDENTIALS")
        self.assertEqual(body_nonexistent["message"], "Email hoặc mật khẩu không đúng")
        self.assertEqual(body_wrong_pw["message"], "Email hoặc mật khẩu không đúng")

        for msg in (body_nonexistent["message"], body_wrong_pw["message"]):
            self.assertNotIn("not found", msg.lower())
            self.assertNotIn("exist", msg.lower())
            self.assertNotIn("password incorrect", msg.lower())

    # 5. Sai lần 1-4 -> tăng failed login counter
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_05_failed_attempts_1_to_4_increment_counter(self, mock_get_user):
        mock_get_user.return_value = self.user

        for attempt in range(1, 5):
            response = self.post_login({
                "email": "trainer.scrum36@daotao.edu.vn",
                "password": "WrongPassword!",
            })
            self.assertEqual(response.status_code, 401)
            self.assertEqual(self.user.failed_login_attempts, attempt)
            self.assertIsNone(self.user.locked_until)

    # 6. Sai lần thứ 5 -> khóa tạm 15 phút
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_06_fifth_failed_attempt_locks_account_15_minutes(self, mock_get_user):
        self.user.failed_login_attempts = 4
        self.user.locked_until = None
        mock_get_user.return_value = self.user

        response = self.post_login({
            "email": "trainer.scrum36@daotao.edu.vn",
            "password": "WrongPassword!",
        })

        self.assertEqual(response.status_code, 403)
        data = response.get_json()
        self.assertEqual(data["code"], "ACCOUNT_LOCKED")
        self.assertIn("Tài khoản tạm thời bị khóa 15 phút", data["message"])
        self.assertIn("locked_until", data)
        self.assertEqual(self.user.failed_login_attempts, 5)
        self.assertIsNotNone(self.user.locked_until)

    # 7. Trong thời gian khóa -> không cho đăng nhập
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_07_locked_account_rejected_even_with_valid_password(self, mock_get_user):
        now = datetime.now(timezone.utc)
        self.user.failed_login_attempts = 5
        self.user.locked_until = now + timedelta(minutes=14)
        mock_get_user.return_value = self.user

        response = self.post_login({
            "email": "trainer.scrum36@daotao.edu.vn",
            "password": "ValidPassword123!",
        })

        self.assertEqual(response.status_code, 403)
        data = response.get_json()
        self.assertEqual(data["code"], "ACCOUNT_LOCKED")
        self.assertIn("locked_until", data)

    # 8. Hết thời gian khóa -> cho thử đăng nhập lại
    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_08_login_permitted_after_lockout_expires(self, mock_get_user, mock_create_session):
        now = datetime.now(timezone.utc)
        self.user.failed_login_attempts = 5
        self.user.locked_until = now - timedelta(seconds=10)
        mock_get_user.return_value = self.user

        with self.app.app_context():
            from app.services.token_service import create_login_tokens
            tokens = create_login_tokens(self.user.id, self.session.session_id)
        mock_create_session.return_value = (self.session, tokens)

        response = self.post_login({
            "email": "trainer.scrum36@daotao.edu.vn",
            "password": "ValidPassword123!",
        })

        self.assertEqual(response.status_code, 200)

    # 9. Đăng nhập thành công -> reset failed login counter
    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_09_successful_login_resets_failed_counter(self, mock_get_user, mock_create_session):
        self.user.failed_login_attempts = 3
        mock_get_user.return_value = self.user

        with self.app.app_context():
            from app.services.token_service import create_login_tokens
            tokens = create_login_tokens(self.user.id, self.session.session_id)
        mock_create_session.return_value = (self.session, tokens)

        response = self.post_login({
            "email": "trainer.scrum36@daotao.edu.vn",
            "password": "ValidPassword123!",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user.failed_login_attempts, 0)
        self.assertIsNone(self.user.locked_until)
        self.mock_reset_lockout.assert_called_once_with(user_id="user-36")

    # 10. Token/session phải sử dụng cơ chế SCRUM-19 hiện có
    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_10_session_and_jwt_tokens_use_scrum19_infrastructure(self, mock_get_user, mock_create_session):
        mock_get_user.return_value = self.user

        with self.app.app_context():
            from app.services.token_service import create_login_tokens
            tokens = create_login_tokens(self.user.id, self.session.session_id)
        mock_create_session.return_value = (self.session, tokens)

        response = self.post_login({
            "email": "trainer.scrum36@daotao.edu.vn",
            "password": "ValidPassword123!",
        })

        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        with self.app.app_context():
            access_claims = decode_token(data["access_token"])
            refresh_claims = decode_token(data["refresh_token"])

        self.assertEqual(access_claims["sub"], "user-36")
        self.assertEqual(access_claims["sid"], "session-scrum36-id")
        self.assertEqual(refresh_claims["sub"], "user-36")
        self.assertEqual(refresh_claims["sid"], "session-scrum36-id")


if __name__ == "__main__":
    unittest.main()
