import unittest
from unittest.mock import MagicMock, patch

from flask import Flask
from mysql.connector import Error as MySQLError

from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.services.auth_service import (
    PUBLIC_FORGOT_PASSWORD_MESSAGE,
    process_forgot_password_request,
)
from app.services.email_service import EmailDeliveryError


class Scrum50AntiEnumerationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True)
        self.app.register_blueprint(auth_bp)
        self.client = self.app.test_client()

        self.mock_user = User(
            id="user-ictu-existing-999",
            email="giangvien@ictu.edu.vn",
            password_hash="pbkdf2:sha256:...",
            role="lecturer",
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

    # =========================================================================
    # 1. Email tồn tại -> response 200 + public message chuẩn
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_existing_email_returns_200_and_public_message(self, mock_get_user):
        mock_get_user.return_value = self.mock_user

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "giangvien@ictu.edu.vn"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"message": PUBLIC_FORGOT_PASSWORD_MESSAGE},
        )

    # =========================================================================
    # 2. Email không tồn tại -> response giống email tồn tại
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_non_existing_email_returns_200_and_identical_response(self, mock_get_user):
        mock_get_user.return_value = None

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "nonexistent@ictu.edu.vn"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"message": PUBLIC_FORGOT_PASSWORD_MESSAGE},
        )

    # =========================================================================
    # 3. So sánh status code của 2 trường hợp
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_compare_status_codes_between_existing_and_non_existing(self, mock_get_user):
        mock_get_user.return_value = self.mock_user
        res_existing = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "giangvien@ictu.edu.vn"},
        )

        mock_get_user.return_value = None
        res_non_existing = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "notfound@ictu.edu.vn"},
        )

        self.assertEqual(res_existing.status_code, res_non_existing.status_code)
        self.assertEqual(res_existing.status_code, 200)

    # =========================================================================
    # 4. So sánh JSON structure của 2 trường hợp
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_compare_json_structure_between_existing_and_non_existing(self, mock_get_user):
        mock_get_user.return_value = self.mock_user
        res_existing = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "giangvien@ictu.edu.vn"},
        )

        mock_get_user.return_value = None
        res_non_existing = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "notfound@ictu.edu.vn"},
        )

        existing_keys = set(res_existing.get_json().keys())
        non_existing_keys = set(res_non_existing.get_json().keys())

        self.assertEqual(existing_keys, non_existing_keys)
        self.assertEqual(existing_keys, {"message"})

    # =========================================================================
    # 5. So sánh message của 2 trường hợp
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_compare_message_between_existing_and_non_existing(self, mock_get_user):
        mock_get_user.return_value = self.mock_user
        res_existing = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "giangvien@ictu.edu.vn"},
        )

        mock_get_user.return_value = None
        res_non_existing = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "notfound@ictu.edu.vn"},
        )

        self.assertEqual(
            res_existing.get_json()["message"],
            res_non_existing.get_json()["message"],
        )
        self.assertEqual(
            res_existing.get_json()["message"],
            PUBLIC_FORGOT_PASSWORD_MESSAGE,
        )

    # =========================================================================
    # 6. Response không chứa: user_id, exists, token, token_hash, reset_url
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_response_never_contains_sensitive_or_enumeration_fields(self, mock_get_user):
        mock_get_user.return_value = self.mock_user

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "giangvien@ictu.edu.vn"},
        )

        raw_response_text = response.get_data(as_text=True)
        data = response.get_json()

        forbidden_keys = [
            "user_id",
            "exists",
            "token",
            "token_hash",
            "reset_url",
            "account_found",
            "user_found",
            "email_exists",
        ]
        for key in forbidden_keys:
            self.assertNotIn(key, data)

        # Kiểm tra không có ID người dùng trong raw text
        self.assertNotIn(self.mock_user.id, raw_response_text)
        self.assertNotIn("token", raw_response_text.lower().replace("đặt lại mật khẩu", ""))
        self.assertNotIn("http", raw_response_text)

    # =========================================================================
    # 7. Email tồn tại mới tạo token
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_token_created_only_when_email_exists(self, mock_get_user):
        mock_get_user.return_value = self.mock_user

        self.client.post(
            "/api/auth/forgot-password",
            json={"email": "giangvien@ictu.edu.vn"},
        )

        self.mock_insert_token.assert_called_once()
        saved_token = self.mock_insert_token.call_args[0][0]
        self.assertEqual(saved_token.user_id, self.mock_user.id)

    # =========================================================================
    # 8. Email không tồn tại không tạo token
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_token_not_created_when_email_does_not_exist(self, mock_get_user):
        mock_get_user.return_value = None

        self.client.post(
            "/api/auth/forgot-password",
            json={"email": "notfound@ictu.edu.vn"},
        )

        self.mock_insert_token.assert_not_called()

    # =========================================================================
    # 9. Email tồn tại mới gọi email service
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_email_service_called_only_when_email_exists(self, mock_get_user):
        mock_get_user.return_value = self.mock_user

        self.client.post(
            "/api/auth/forgot-password",
            json={"email": "giangvien@ictu.edu.vn"},
        )

        self.mock_send_email.assert_called_once()
        self.assertEqual(
            self.mock_send_email.call_args.kwargs["to_email"],
            self.mock_user.email,
        )

    # =========================================================================
    # 10. Email không tồn tại không gọi email service
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_email_service_not_called_when_email_does_not_exist(self, mock_get_user):
        mock_get_user.return_value = None

        self.client.post(
            "/api/auth/forgot-password",
            json={"email": "notfound@ictu.edu.vn"},
        )

        self.mock_send_email.assert_not_called()

    # =========================================================================
    # 11. SMTP failure không làm thay đổi public response theo trạng thái tài khoản
    # =========================================================================
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_smtp_failure_does_not_alter_public_response(self, mock_get_user):
        mock_get_user.return_value = self.mock_user
        self.mock_send_email.side_effect = EmailDeliveryError("SMTP connection dropped")

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "giangvien@ictu.edu.vn"},
        )

        # Phải trả về cùng status 200 và message chung
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"message": PUBLIC_FORGOT_PASSWORD_MESSAGE},
        )

    # =========================================================================
    # 12. Validation email sai vẫn trả lỗi 400 phù hợp
    # =========================================================================
    def test_invalid_email_format_or_missing_email_returns_400(self):
        # Thiếu email field
        res1 = self.client.post("/api/auth/forgot-password", json={})
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json()["code"], "EMAIL_REQUIRED")

        # Email rỗng
        res2 = self.client.post("/api/auth/forgot-password", json={"email": "   "})
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "EMAIL_REQUIRED")

        # Email sai định dạng regex
        res3 = self.client.post("/api/auth/forgot-password", json={"email": "not-an-email"})
        self.assertEqual(res3.status_code, 400)
        self.assertEqual(res3.get_json()["code"], "INVALID_EMAIL")


if __name__ == "__main__":
    unittest.main()
