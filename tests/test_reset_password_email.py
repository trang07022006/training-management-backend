import hashlib
import logging
import os
import smtplib
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from flask import Flask

from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.services import email_service
from app.services.auth_service import (
    PUBLIC_FORGOT_PASSWORD_MESSAGE,
    hash_reset_token,
    process_forgot_password_request,
)
from app.services.email_service import (
    EmailDeliveryError,
    build_account_creation_email_content,
    build_reset_password_email_content,
    build_reset_password_url,
    get_smtp_config,
    send_account_creation_email,
    send_email,
    send_password_reset_email,
)


class Scrum48PasswordResetEmailTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True)
        self.app.register_blueprint(auth_bp)
        self.client = self.app.test_client()

        self.mock_user = User(
            id="user-ictu-lecturer-101",
            email="giangvien@ictu.edu.vn",
            password_hash="pbkdf2:sha256:...",
            role="lecturer",
            status="active",
        )

    # =========================================================================
    # 1. Email tồn tại: tạo token, gọi email service đúng 1 lần
    # =========================================================================
    @patch("app.services.auth_service.email_service.send_password_reset_email")
    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_existing_email_creates_token_and_sends_email_exactly_once(
        self, mock_get_user, mock_insert_token, mock_send_email
    ):
        mock_get_user.return_value = self.mock_user

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "giangvien@ictu.edu.vn"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["message"],
            PUBLIC_FORGOT_PASSWORD_MESSAGE,
        )

        # Kiểm tra token được tạo và lưu vào database đúng 1 lần
        mock_insert_token.assert_called_once()
        saved_token: PasswordResetToken = mock_insert_token.call_args[0][0]

        # Kiểm tra email service được gọi đúng 1 lần
        mock_send_email.assert_called_once()
        call_kwargs = mock_send_email.call_args.kwargs
        self.assertEqual(call_kwargs["to_email"], self.mock_user.email)
        raw_token_sent = call_kwargs["raw_token"]
        self.assertIsInstance(raw_token_sent, str)
        self.assertGreaterEqual(len(raw_token_sent), 32)

        # Token hash trong database phải khớp với hash của raw_token đã gửi qua email
        expected_hash = hashlib.sha256(raw_token_sent.encode("utf-8")).hexdigest()
        self.assertEqual(saved_token.token_hash, expected_hash)

    # =========================================================================
    # 2. Email không tồn tại: không gửi email, vẫn trả public response
    # =========================================================================
    @patch("app.services.auth_service.email_service.send_password_reset_email")
    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_non_existing_email_does_not_send_email_and_returns_same_public_message(
        self, mock_get_user, mock_insert_token, mock_send_email
    ):
        mock_get_user.return_value = None

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "notfound@ictu.edu.vn"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["message"],
            PUBLIC_FORGOT_PASSWORD_MESSAGE,
        )

        # Không tạo token và tuyệt đối không gửi email
        mock_insert_token.assert_not_called()
        mock_send_email.assert_not_called()

    # =========================================================================
    # 3. Reset URL: chứa đúng route reset-password và raw token
    # =========================================================================
    def test_reset_url_format_and_route(self):
        raw_token = "secure_random_token_abcdef123456"

        with patch.dict(os.environ, {"FRONTEND_URL": "http://localhost:5173"}):
            url = build_reset_password_url(raw_token)
            self.assertEqual(url, f"http://localhost:5173/reset-password?token={raw_token}")
            self.assertIn("/reset-password", url)
            self.assertIn(f"?token={raw_token}", url)

        # Test với FRONTEND_URL tùy chỉnh không có dấu gạch chéo cuối
        with patch.dict(os.environ, {"FRONTEND_URL": "https://daotao.ictu.edu.vn"}):
            url2 = build_reset_password_url(raw_token)
            self.assertEqual(url2, f"https://daotao.ictu.edu.vn/reset-password?token={raw_token}")

        # Test với FRONTEND_URL có dấu gạch chéo cuối (đảm bảo không bị lặp //)
        with patch.dict(os.environ, {"FRONTEND_URL": "https://daotao.ictu.edu.vn/"}):
            url3 = build_reset_password_url(raw_token)
            self.assertEqual(url3, f"https://daotao.ictu.edu.vn/reset-password?token={raw_token}")

    # =========================================================================
    # 4. Database: chỉ lưu token_hash, không lưu raw token
    # =========================================================================
    @patch("app.services.auth_service.email_service.send_password_reset_email")
    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_database_only_stores_token_hash_not_raw_token(
        self, mock_get_user, mock_insert_token, mock_send_email
    ):
        mock_get_user.return_value = self.mock_user

        process_forgot_password_request("giangvien@ictu.edu.vn")

        mock_insert_token.assert_called_once()
        saved_token: PasswordResetToken = mock_insert_token.call_args[0][0]

        mock_send_email.assert_called_once()
        raw_token_sent = mock_send_email.call_args.kwargs["raw_token"]

        # Database chỉ có trường token_hash 64 ký tự hex
        self.assertEqual(len(saved_token.token_hash), 64)
        self.assertNotEqual(saved_token.token_hash, raw_token_sent)
        self.assertFalse(hasattr(saved_token, "raw_token"))
        self.assertFalse(hasattr(saved_token, "token"))

    # =========================================================================
    # 5. Public response: không chứa token, không chứa reset URL, không chứa user_id
    # =========================================================================
    @patch("app.services.auth_service.email_service.send_password_reset_email")
    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_public_response_never_contains_sensitive_data(
        self, mock_get_user, mock_insert_token, mock_send_email
    ):
        mock_get_user.return_value = self.mock_user

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "giangvien@ictu.edu.vn"},
        )

        data = response.get_json()
        raw_text = response.get_data(as_text=True)

        self.assertEqual(list(data.keys()), ["message"])
        self.assertNotIn("token", raw_text.lower().replace("đặt lại mật khẩu", ""))
        self.assertNotIn("reset-password", raw_text)
        self.assertNotIn("http", raw_text)
        self.assertNotIn(self.mock_user.id, raw_text)

    # =========================================================================
    # 6. Email content: có reset link, có thông báo hết hạn 30 phút, ngôn ngữ Tiếng Việt
    # =========================================================================
    def test_email_content_contains_link_and_30_minutes_notice(self):
        sample_url = "http://localhost:5173/reset-password?token=sample_token_xyz"
        subject, text_body, html_body = build_reset_password_email_content(sample_url)

        # Tiêu đề
        self.assertIn("Hệ thống Quản lý Đào tạo", subject)
        self.assertIn("đặt lại mật khẩu", subject.lower())

        # Plain text
        self.assertIn(sample_url, text_body)
        self.assertIn("30 phút", text_body)
        self.assertIn("bỏ qua email", text_body)

        # HTML
        self.assertIn(sample_url, html_body)
        self.assertIn("30 phút", html_body)
        self.assertIn("href=", html_body)
        self.assertIn("bỏ qua email", html_body)

        # Không chứa mật khẩu cũ hoặc thông tin nhạy cảm
        self.assertNotIn("password_hash", text_body)
        self.assertNotIn("pbkdf2", html_body)

    # =========================================================================
    # 7. SMTP config: đọc từ environment variables, không hard-code credentials
    # =========================================================================
    def test_smtp_config_reads_from_environment_variables(self):
        custom_env = {
            "SMTP_HOST": "smtp.ictu.edu.vn",
            "SMTP_PORT": "465",
            "SMTP_USERNAME": "ictu_mailer",
            "SMTP_PASSWORD": "SecretMailerPassword999",
            "SMTP_FROM_EMAIL": "daotao@ictu.edu.vn",
            "SMTP_USE_TLS": "false",
            "SMTP_USE_SSL": "true",
        }

        with patch.dict(os.environ, custom_env):
            config = get_smtp_config()
            self.assertEqual(config["host"], "smtp.ictu.edu.vn")
            self.assertEqual(config["port"], 465)
            self.assertEqual(config["username"], "ictu_mailer")
            self.assertEqual(config["password"], "SecretMailerPassword999")
            self.assertEqual(config["from_email"], "daotao@ictu.edu.vn")
            self.assertFalse(config["use_tls"])
            self.assertTrue(config["use_ssl"])

    # =========================================================================
    # 8. SMTP / email service failure: xử lý an toàn, không leak thông tin nhạy cảm
    # =========================================================================
    @patch("app.services.auth_service.email_service.send_password_reset_email")
    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_smtp_failure_handled_safely_and_preserves_anti_enumeration(
        self, mock_get_user, mock_insert_token, mock_send_email
    ):
        mock_get_user.return_value = self.mock_user
        mock_send_email.side_effect = EmailDeliveryError("Connection refused by SMTP server")

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "giangvien@ictu.edu.vn"},
        )

        # Phải trả về 200 với thông báo chung (chống dò email)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["message"], PUBLIC_FORGOT_PASSWORD_MESSAGE)

        # Không rò rỉ chi tiết lỗi SMTP ra ngoài
        raw_text = response.get_data(as_text=True)
        self.assertNotIn("Connection refused", raw_text)
        self.assertNotIn("SMTP", raw_text)

    # =========================================================================
    # 9. Không log raw token hoặc SMTP secret khi có lỗi
    # =========================================================================
    @patch("app.services.auth_service.email_service.send_password_reset_email")
    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_logging_does_not_leak_raw_token_or_secret(
        self, mock_get_user, mock_insert_token, mock_send_email
    ):
        mock_get_user.return_value = self.mock_user
        mock_send_email.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")

        with self.assertLogs("app.services.auth_service", level="ERROR") as log_cm:
            response = self.client.post(
                "/api/auth/forgot-password",
                json={"email": "giangvien@ictu.edu.vn"},
            )

        self.assertEqual(response.status_code, 200)
        logged_text = " ".join(log_cm.output)

        # Lấy raw_token đã sinh
        raw_token_sent = mock_send_email.call_args.kwargs["raw_token"]

        # Tuyệt đối không log raw_token
        self.assertNotIn(raw_token_sent, logged_text)
        self.assertNotIn("SecretMailerPassword", logged_text)

    # =========================================================================
    # 10. Gửi email qua SMTP client mock: kiểm tra TLS, login, send_message
    # =========================================================================
    @patch("smtplib.SMTP")
    def test_send_email_uses_smtp_client_correctly(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        custom_env = {
            "SMTP_HOST": "smtp.test.ictu.edu.vn",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "test_user",
            "SMTP_PASSWORD": "test_password",
            "SMTP_FROM_EMAIL": "test-noreply@ictu.edu.vn",
            "SMTP_USE_TLS": "true",
            "SMTP_USE_SSL": "false",
        }

        with patch.dict(os.environ, custom_env):
            send_password_reset_email(
                to_email="sinhvien@ictu.edu.vn",
                raw_token="token_test_12345",
            )

        mock_smtp_cls.assert_called_once_with("smtp.test.ictu.edu.vn", 587, timeout=10)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("test_user", "test_password")
        mock_server.send_message.assert_called_once()
        mock_server.quit.assert_called_once()

        sent_msg = mock_server.send_message.call_args[0][0]
        self.assertEqual(sent_msg["To"], "sinhvien@ictu.edu.vn")
        self.assertEqual(sent_msg["From"], "test-noreply@ictu.edu.vn")
        self.assertIn("Yêu cầu đặt lại mật khẩu", sent_msg["Subject"])

    # =========================================================================
    # 11. Email tạo tài khoản mới: kiểm tra tiêu đề, nội dung và mật khẩu ban đầu
    # =========================================================================
    def test_account_creation_email_content(self):
        subject, text_body, html_body = build_account_creation_email_content(
            to_email="newuser@ictu.edu.vn",
            name="Nguyễn Văn B",
            raw_password="InitialPassword123",
            login_url="http://localhost:5173/login",
        )

        self.assertIn("Thông tin tài khoản mới", subject)
        self.assertIn("Nguyễn Văn B", text_body)
        self.assertIn("newuser@ictu.edu.vn", text_body)
        self.assertIn("InitialPassword123", text_body)
        self.assertIn("http://localhost:5173/login", text_body)

        self.assertIn("Nguyễn Văn B", html_body)
        self.assertIn("newuser@ictu.edu.vn", html_body)
        self.assertIn("InitialPassword123", html_body)
        self.assertIn("http://localhost:5173/login", html_body)

    @patch("smtplib.SMTP")
    def test_send_account_creation_email(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        custom_env = {
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "lletrang070206@gmail.com",
            "SMTP_PASSWORD": "app_password_mock",
            "SMTP_FROM_EMAIL": "lletrang070206@gmail.com",
            "SMTP_USE_TLS": "true",
            "SMTP_USE_SSL": "false",
        }

        with patch.dict(os.environ, custom_env):
            send_account_creation_email(
                to_email="hocvien@ictu.edu.vn",
                name="Trần Văn C",
                raw_password="SecurePass789",
            )

        mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=10)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("lletrang070206@gmail.com", "app_password_mock")
        mock_server.send_message.assert_called_once()

        sent_msg = mock_server.send_message.call_args[0][0]
        self.assertEqual(sent_msg["To"], "hocvien@ictu.edu.vn")
        self.assertEqual(sent_msg["From"], "lletrang070206@gmail.com")
        self.assertIn("Thông tin tài khoản mới", sent_msg["Subject"])


if __name__ == "__main__":
    unittest.main()

