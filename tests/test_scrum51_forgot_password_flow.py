import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from flask import Flask
from werkzeug.security import check_password_hash, generate_password_hash

from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.services.auth_service import (
    PUBLIC_FORGOT_PASSWORD_MESSAGE,
    create_password_reset_token,
    generate_reset_token,
    hash_reset_token,
    process_forgot_password_request,
    reset_password_with_token,
    validate_reset_token,
)
from app.services.email_service import (
    build_reset_password_email_content,
    build_reset_password_url,
)


class Scrum51OverallForgotPasswordFlowTests(unittest.TestCase):
    """
    Kiểm thử tổng thể SCRUM-51 cho chức năng Quên và Đặt lại mật khẩu:
    Flow:
      Login
      -> Quên mật khẩu
      -> Nhập email
      -> forgot-password API
      -> Tạo reset token (30 phút, cryptographic random, hash SHA-256)
      -> Gửi email chứa reset link
      -> Mở Reset Password
      -> Validate password mới (độ dài, ký tự chữ + số)
      -> Reset password API
      -> Password hash được cập nhật trong DB
      -> Token chỉ dùng 1 lần (used_at được ghi nhận)
      -> Quay lại Login
      -> Đăng nhập bằng mật khẩu mới thành công
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum51",
        )
        self.app.register_blueprint(auth_bp)
        self.client = self.app.test_client()

        self.fixed_now = datetime.now(timezone.utc)
        self.test_email = "teacher@ictu.edu.vn"
        self.initial_password = "OldPassword123!"
        self.new_password = "NewSecurePassword456!"
        self.user_id = "user-ictu-51"

        self.user = User(
            id=self.user_id,
            email=self.test_email,
            password_hash=generate_password_hash(self.initial_password),
            role="teacher",
            status="active",
        )

    # =========================================================================
    # 1. Full E2E Flow: Forgot -> Reset -> Single-use -> Login with new pass
    # =========================================================================
    def test_complete_end_to_end_forgot_reset_and_login_flow(self):
        """Kiểm tra toàn bộ chu trình hoàn chỉnh theo đúng nghiệp vụ SCRUM-51."""
        captured_emails = []
        tokens_db = {}
        users_db = {
            self.test_email: {
                "id": self.user_id,
                "email": self.test_email,
                "password_hash": self.user.password_hash,
                "role": "teacher",
                "status": "active",
                "failed_login_attempts": 0,
                "locked_until": None,
            }
        }

        # Step 1: User gửi yêu cầu Quên mật khẩu
        def fake_get_user_by_email(email):
            data = users_db.get(email.lower())
            if not data:
                return None
            return User(
                id=data["id"],
                email=data["email"],
                password_hash=data["password_hash"],
                role=data["role"],
                status=data["status"],
                failed_login_attempts=data["failed_login_attempts"],
                locked_until=data["locked_until"],
            )

        def fake_insert_token(token_record):
            tokens_db[token_record.token_hash] = {
                "id": token_record.id,
                "user_id": token_record.user_id,
                "token_hash": token_record.token_hash,
                "created_at": token_record.created_at,
                "expires_at": token_record.expires_at,
                "used_at": token_record.used_at,
            }

        def fake_send_email(to_email, raw_token, reset_url=None):
            url = reset_url or build_reset_password_url(raw_token)
            captured_emails.append({
                "to": to_email,
                "token": raw_token,
                "url": url,
            })

        with patch("app.repositories.user_repository.get_user_by_email", side_effect=fake_get_user_by_email), \
             patch("app.repositories.password_reset_repository.insert_reset_token", side_effect=fake_insert_token), \
             patch("app.services.email_service.send_password_reset_email", side_effect=fake_send_email):

            # 1.1 POST /api/auth/forgot-password
            res_forgot = self.client.post(
                "/api/auth/forgot-password",
                json={"email": "  TEACHER@ictu.edu.vn  "},  # Kiểm tra tự động normalize
            )
            self.assertEqual(res_forgot.status_code, 200)
            self.assertEqual(res_forgot.get_json(), {"message": PUBLIC_FORGOT_PASSWORD_MESSAGE})

            # Không làm lộ các trường nhạy cảm trong response
            for sensitive_key in ("user_id", "exists", "token", "token_hash", "reset_url"):
                self.assertNotIn(sensitive_key, res_forgot.get_json())

            # 1.2 Kiểm tra email được gửi chứa reset URL và token
            self.assertEqual(len(captured_emails), 1)
            sent_email = captured_emails[0]
            self.assertEqual(sent_email["to"], self.test_email)
            raw_token = sent_email["token"]
            self.assertIn("/reset-password?token=", sent_email["url"])
            self.assertIn(raw_token, sent_email["url"])

            # 1.3 Kiểm tra token lưu trong DB dưới dạng hash, không lưu raw token
            token_hash = hash_reset_token(raw_token)
            self.assertIn(token_hash, tokens_db)
            self.assertNotIn(raw_token, tokens_db)

            # 1.4 Mở Reset Password -> Gọi verify-reset-token
            with patch("app.repositories.password_reset_repository.get_reset_token_by_hash") as mock_get_hash:
                token_row = tokens_db[token_hash]
                mock_get_hash.return_value = PasswordResetToken(
                    id=token_row["id"],
                    user_id=token_row["user_id"],
                    token_hash=token_row["token_hash"],
                    created_at=token_row["created_at"],
                    expires_at=token_row["expires_at"],
                    used_at=token_row["used_at"],
                )
                res_verify = self.client.post(
                    "/api/auth/verify-reset-token",
                    json={"token": raw_token},
                )
                self.assertEqual(res_verify.status_code, 200)
                self.assertTrue(res_verify.get_json()["valid"])

            # 1.5 Nhập mật khẩu mới -> Gọi POST /api/auth/reset-password
            with patch("app.repositories.password_reset_repository.get_db_connection") as mock_conn:
                fake_conn = MagicMock()
                fake_cursor = MagicMock()
                fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
                mock_conn.return_value = fake_conn

                def fake_db_execute(sql, params):
                    if "SELECT" in sql and "FROM password_reset_tokens" in sql:
                        t_hash = params[0]
                        fake_cursor.fetchone.return_value = tokens_db.get(t_hash)
                    elif "UPDATE users" in sql:
                        new_hash, uid = params[0], params[1]
                        for user_data in users_db.values():
                            if user_data["id"] == uid:
                                user_data["password_hash"] = new_hash
                                user_data["failed_login_attempts"] = 0
                                user_data["locked_until"] = None
                        fake_cursor.rowcount = 1
                    elif "UPDATE password_reset_tokens" in sql:
                        used_val, tid = params[0], params[1]
                        for t in tokens_db.values():
                            if t["id"] == tid:
                                t["used_at"] = self.fixed_now
                        fake_cursor.rowcount = 1

                fake_cursor.execute.side_effect = fake_db_execute

                res_reset = self.client.post(
                    "/api/auth/reset-password",
                    json={
                        "token": raw_token,
                        "new_password": self.new_password,
                    },
                )
                self.assertEqual(res_reset.status_code, 200)
                self.assertIn("thành công", res_reset.get_json()["message"])

                # Kiểm tra password trong DB đã được hash, không lưu plaintext
                updated_user = users_db[self.test_email]
                self.assertNotEqual(updated_user["password_hash"], self.new_password)
                self.assertTrue(check_password_hash(updated_user["password_hash"], self.new_password))

                # Kiểm tra token đã được consume (used_at != None)
                self.assertIsNotNone(tokens_db[token_hash]["used_at"])

                # 1.6 Thử dùng lại token lần hai -> Bị từ chối (Single-use)
                res_reuse = self.client.post(
                    "/api/auth/reset-password",
                    json={
                        "token": raw_token,
                        "new_password": "AnotherPassword789!",
                    },
                )
                self.assertEqual(res_reuse.status_code, 400)
                self.assertEqual(res_reuse.get_json()["code"], "TOKEN_ALREADY_USED")

            # 1.7 Thử đăng nhập lại bằng mật khẩu cũ -> Thất bại (401)
            with patch("app.services.auth_service.user_repository.get_user_by_email", side_effect=fake_get_user_by_email), \
                 patch("app.services.auth_service.user_repository.update_user_lockout"):
                res_login_old = self.client.post(
                    "/api/auth/login",
                    json={
                        "email": self.test_email,
                        "password": self.initial_password,
                    },
                )
                self.assertEqual(res_login_old.status_code, 401)
                self.assertEqual(res_login_old.get_json()["code"], "INVALID_CREDENTIALS")

            # 1.8 Đăng nhập lại bằng mật khẩu mới -> Thành công (200)
            with patch("app.services.auth_service.user_repository.get_user_by_email", side_effect=fake_get_user_by_email), \
                 patch("app.services.auth_service.user_repository.reset_user_lockout"), \
                 patch("app.services.auth_service.create_stored_login_session") as mock_session:

                mock_session.return_value = (
                    MagicMock(
                        session_id="session-51-abc",
                        idle_expires_at=self.fixed_now + timedelta(minutes=15),
                        absolute_expires_at=self.fixed_now + timedelta(hours=8),
                    ),
                    {
                        "access_token": "fake-access-token",
                        "refresh_token": "fake-refresh-token",
                    },
                )

                with patch("app.routes.auth_routes.decode_token", return_value={"exp": 1727712000}):
                    res_login_new = self.client.post(
                        "/api/auth/login",
                        json={
                            "email": self.test_email,
                            "password": self.new_password,
                        },
                    )
                    self.assertEqual(res_login_new.status_code, 200)
                    login_data = res_login_new.get_json()
                    self.assertEqual(login_data["user"]["email"], self.test_email)
                    self.assertEqual(login_data["session_id"], "session-51-abc")

    # =========================================================================
    # 2. Password Strength & Rule Validation
    # =========================================================================
    def test_reset_password_rejects_weak_and_invalid_passwords(self):
        """Mật khẩu dưới 8 ký tự hoặc thiếu chữ/số phải bị từ chối 400."""
        # Quá ngắn (< 8 ký tự)
        res_short = self.client.post(
            "/api/auth/reset-password",
            json={
                "token": "some-token",
                "new_password": "Abc1",
            },
        )
        self.assertEqual(res_short.status_code, 400)
        self.assertEqual(res_short.get_json()["code"], "PASSWORD_TOO_SHORT")

        # Toàn chữ, không có số
        res_no_digit = self.client.post(
            "/api/auth/reset-password",
            json={
                "token": "some-token",
                "new_password": "OnlyLettersHere",
            },
        )
        self.assertEqual(res_no_digit.status_code, 400)
        self.assertEqual(res_no_digit.get_json()["code"], "PASSWORD_INVALID")

        # Toàn số, không có chữ
        res_no_letter = self.client.post(
            "/api/auth/reset-password",
            json={
                "token": "some-token",
                "new_password": "1234567890123",
            },
        )
        self.assertEqual(res_no_letter.status_code, 400)
        self.assertEqual(res_no_letter.get_json()["code"], "PASSWORD_INVALID")

    # =========================================================================
    # 3. Token Generation & Expiry
    # =========================================================================
    def test_token_cryptographic_randomness_and_expiry_duration(self):
        """Token sinh bằng secrets cryptographically secure, thời hạn đúng 30 phút."""
        tokens = {generate_reset_token() for _ in range(50)}
        self.assertEqual(len(tokens), 50)  # Tất cả đều duy nhất

        with patch("app.repositories.password_reset_repository.insert_reset_token"):
            raw_t, record = create_password_reset_token(
                user_id=self.user_id,
                current_time=self.fixed_now,
            )
            # Đúng 30 phút
            self.assertEqual(record.expires_at - record.created_at, timedelta(minutes=30))
            # Chưa hết hạn tại thời điểm hiện tại
            self.assertFalse(record.is_expired(current_time=self.fixed_now))
            # Hết hạn tại thời điểm 30 phút 1 giây
            self.assertTrue(record.is_expired(current_time=self.fixed_now + timedelta(minutes=30, seconds=1)))

    # =========================================================================
    # 4. Anti-enumeration and Public Response Symmetry
    # =========================================================================
    @patch("app.repositories.user_repository.get_user_by_email")
    @patch("app.repositories.password_reset_repository.insert_reset_token")
    @patch("app.services.email_service.send_password_reset_email")
    def test_public_response_symmetry_and_security(
        self, mock_email, mock_token, mock_get_user
    ):
        """Email tồn tại và không tồn tại trả cùng HTTP status, JSON structure, message."""
        mock_get_user.return_value = self.user
        res_exist = self.client.post(
            "/api/auth/forgot-password",
            json={"email": self.test_email},
        )

        mock_get_user.return_value = None
        res_non_exist = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "nonexistent@ictu.edu.vn"},
        )

        self.assertEqual(res_exist.status_code, 200)
        self.assertEqual(res_non_exist.status_code, 200)
        self.assertEqual(res_exist.get_json(), res_non_exist.get_json())
        self.assertEqual(res_exist.headers.get("Content-Type"), res_non_exist.headers.get("Content-Type"))

        # Kiểm tra email service chỉ gọi khi user tồn tại
        self.assertEqual(mock_email.call_count, 1)
        self.assertEqual(mock_token.call_count, 1)

    # =========================================================================
    # 5. Email Content Security
    # =========================================================================
    def test_email_content_contains_30m_notice_and_no_sensitive_secrets(self):
        """Nội dung email nêu rõ thời hạn 30 phút và không chứa raw token hay password ngoài URL."""
        test_url = "http://localhost:5173/reset-password?token=safe-token-test-123"
        subject, text_body, html_body = build_reset_password_email_content(test_url)

        self.assertIn("30 phút", text_body)
        self.assertIn("30 phút", html_body)
        self.assertIn(test_url, text_body)
        self.assertIn(test_url, html_body)

        # Không chứa mật khẩu hay thông tin nhạy cảm
        for forbidden in ("password_hash", "SMTP_PASSWORD", "secret", "user_id"):
            self.assertNotIn(forbidden, text_body)
            self.assertNotIn(forbidden, html_body)


if __name__ == "__main__":
    unittest.main()
