import unittest
from unittest.mock import MagicMock, patch

from flask import Flask
from mysql.connector import Error as MySQLError

from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.services.auth_service import (
    AuthValidationError,
    PUBLIC_FORGOT_PASSWORD_MESSAGE,
    process_forgot_password_request,
)


class ForgotPasswordApiTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True)
        self.app.register_blueprint(auth_bp)
        self.client = self.app.test_client()

        self.mock_user = User(
            id="user-ictu-001",
            email="admin@ictu.edu.vn",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            status="active",
        )

        self.patch_insert_token = patch(
            "app.services.auth_service.password_reset_repository.insert_reset_token"
        )
        self.mock_insert_token = self.patch_insert_token.start()
        self.addCleanup(self.patch_insert_token.stop)

        self.patch_send_email = patch(
            "app.services.auth_service.email_service.send_password_reset_email"
        )
        self.mock_send_email = self.patch_send_email.start()
        self.addCleanup(self.patch_send_email.stop)

    def post_forgot_password(self, data=None, content_type="application/json"):
        if data is None:
            data = {"email": "admin@ictu.edu.vn"}

        return self.client.post(
            "/api/auth/forgot-password",
            json=data if content_type == "application/json" else None,
            data=data if content_type != "application/json" else None,
            content_type=content_type,
        )

    # =========================================================================
    # 1. Email hợp lệ
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_valid_email_returns_200_and_public_message(self, mock_get_user):
        mock_get_user.return_value = self.mock_user

        response = self.post_forgot_password({"email": "admin@ictu.edu.vn"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("message", data)
        self.assertEqual(data["message"], PUBLIC_FORGOT_PASSWORD_MESSAGE)
        mock_get_user.assert_called_once_with("admin@ictu.edu.vn")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_valid_email_normalized_with_spaces_and_uppercase(self, mock_get_user):
        mock_get_user.return_value = self.mock_user

        response = self.post_forgot_password({"email": "   Admin@ICTU.edu.vn   "})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["message"], PUBLIC_FORGOT_PASSWORD_MESSAGE)
        # Xác nhận email đã được chuẩn hóa (strip & lowercase) trước khi truy vấn
        mock_get_user.assert_called_once_with("admin@ictu.edu.vn")

    # =========================================================================
    # 2. Thiếu email
    # =========================================================================
    def test_missing_email_field_returns_400(self):
        response = self.post_forgot_password({})

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["code"], "EMAIL_REQUIRED")

    def test_null_email_returns_400(self):
        response = self.post_forgot_password({"email": None})

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["code"], "EMAIL_REQUIRED")

    def test_empty_email_string_returns_400(self):
        response = self.post_forgot_password({"email": ""})

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["code"], "EMAIL_REQUIRED")

    def test_whitespace_only_email_returns_400(self):
        response = self.post_forgot_password({"email": "     "})

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["code"], "EMAIL_REQUIRED")

    def test_non_string_email_returns_400(self):
        response = self.post_forgot_password({"email": 12345})

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["code"], "EMAIL_REQUIRED")

    def test_non_json_payload_returns_400(self):
        response = self.client.post(
            "/api/auth/forgot-password",
            data="email=admin@ictu.edu.vn",
            content_type="text/plain",
        )

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["code"], "INVALID_REQUEST")

    # =========================================================================
    # 3. Email sai định dạng
    # =========================================================================
    def test_invalid_email_format_no_at_returns_400(self):
        response = self.post_forgot_password({"email": "notanemail"})

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["code"], "INVALID_EMAIL")

    def test_invalid_email_format_no_username_returns_400(self):
        response = self.post_forgot_password({"email": "@ictu.edu.vn"})

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["code"], "INVALID_EMAIL")

    def test_invalid_email_format_no_tld_returns_400(self):
        response = self.post_forgot_password({"email": "admin@ictu"})

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["code"], "INVALID_EMAIL")

    def test_invalid_email_format_consecutive_dots_returns_400(self):
        response = self.post_forgot_password({"email": "admin@ictu..vn"})

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["code"], "INVALID_EMAIL")

    # =========================================================================
    # 4. Email tồn tại
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_existing_user_email_returns_success_message(self, mock_get_user):
        mock_get_user.return_value = self.mock_user

        response = self.post_forgot_password({"email": "admin@ictu.edu.vn"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["message"], PUBLIC_FORGOT_PASSWORD_MESSAGE)
        mock_get_user.assert_called_once_with("admin@ictu.edu.vn")

    # =========================================================================
    # 5. Email không tồn tại
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_non_existing_user_email_returns_success_message(self, mock_get_user):
        mock_get_user.return_value = None

        response = self.post_forgot_password({"email": "stranger@ictu.edu.vn"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["message"], PUBLIC_FORGOT_PASSWORD_MESSAGE)
        mock_get_user.assert_called_once_with("stranger@ictu.edu.vn")

    # =========================================================================
    # 6. Response không tiết lộ tài khoản (Anti-enumeration)
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_anti_enumeration_identical_response_for_existing_and_non_existing(
        self, mock_get_user
    ):
        # 1. Yêu cầu với email tồn tại
        mock_get_user.return_value = self.mock_user
        res_existing = self.post_forgot_password({"email": "admin@ictu.edu.vn"})

        # 2. Yêu cầu với email không tồn tại
        mock_get_user.return_value = None
        res_non_existing = self.post_forgot_password({"email": "notfound@ictu.edu.vn"})

        # So sánh status code
        self.assertEqual(res_existing.status_code, 200)
        self.assertEqual(res_non_existing.status_code, 200)
        self.assertEqual(res_existing.status_code, res_non_existing.status_code)

        # So sánh cấu trúc JSON và nội dung thông báo
        data_existing = res_existing.get_json()
        data_non_existing = res_non_existing.get_json()

        self.assertEqual(data_existing, data_non_existing)
        self.assertEqual(
            data_existing["message"],
            "Nếu email tồn tại trong hệ thống, hướng dẫn đặt lại mật khẩu sẽ được gửi tới email của bạn.",
        )

        # Không chứa các trường làm lộ dữ liệu người dùng
        for key in ("user", "user_id", "exists", "token", "devResetLink", "resetLink"):
            self.assertNotIn(key, data_existing)
            self.assertNotIn(key, data_non_existing)

    # =========================================================================
    # 7. Lỗi database không dùng mock
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_database_mysql_error_returns_500_without_mock_fallback(self, mock_get_user):
        # Giả lập MySQL ném lỗi kết nối
        mock_get_user.side_effect = MySQLError("Can't connect to MySQL server on '127.0.0.1'")

        response = self.post_forgot_password({"email": "admin@ictu.edu.vn"})

        # Phải trả về lỗi 500, KHÔNG fallback về 200 thành công bằng mock
        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertEqual(data["code"], "DATABASE_ERROR")
        self.assertNotIn(PUBLIC_FORGOT_PASSWORD_MESSAGE, str(data))

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_database_generic_exception_returns_500_without_mock_fallback(
        self, mock_get_user
    ):
        mock_get_user.side_effect = Exception("Database timeout")

        response = self.post_forgot_password({"email": "admin@ictu.edu.vn"})

        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertEqual(data["code"], "DATABASE_ERROR")


class ForgotPasswordServiceUnitTests(unittest.TestCase):
    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_service_valid_email(self, mock_get_user, mock_insert_token):
        mock_get_user.return_value = User(
            id="u1",
            email="user@example.com",
            password_hash="hash",
        )
        result = process_forgot_password_request("User@Example.com  ")
        self.assertEqual(result["message"], PUBLIC_FORGOT_PASSWORD_MESSAGE)
        mock_get_user.assert_called_once_with("user@example.com")
        mock_insert_token.assert_called_once()

    def test_service_empty_email_raises_validation_error(self):
        with self.assertRaises(AuthValidationError) as ctx:
            process_forgot_password_request("   ")
        self.assertEqual(ctx.exception.code, "EMAIL_REQUIRED")

    def test_service_invalid_email_raises_validation_error(self):
        with self.assertRaises(AuthValidationError) as ctx:
            process_forgot_password_request("invalid_email")
        self.assertEqual(ctx.exception.code, "INVALID_EMAIL")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_service_database_exception_propagates(self, mock_get_user):
        mock_get_user.side_effect = RuntimeError("DB down")
        with self.assertRaises(RuntimeError):
            process_forgot_password_request("valid@ictu.edu.vn")


if __name__ == "__main__":
    unittest.main()
