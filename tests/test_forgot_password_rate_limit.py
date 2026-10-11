from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.services.auth_service import (
    FORGOT_PASSWORD_COOLDOWN_MESSAGE,
    FORGOT_PASSWORD_COOLDOWN_SECONDS,
    PUBLIC_FORGOT_PASSWORD_MESSAGE,
    RESET_TOKEN_DURATION,
    clear_forgot_password_rate_limits,
    create_password_reset_token,
    process_forgot_password_request,
)


class ForgotPasswordRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True)
        self.app.register_blueprint(auth_bp)
        self.client = self.app.test_client()

        clear_forgot_password_rate_limits()

        self.mock_user = User(
            id="user-ictu-rate-limit-test",
            email="developer@ictu.edu.vn",
            password_hash="pbkdf2:sha256:...",
            role="lecturer",
            status="active",
        )

        self.patch_send_email = patch(
            "app.services.auth_service.email_service.send_password_reset_email"
        )
        self.mock_send_email = self.patch_send_email.start()
        self.addCleanup(self.patch_send_email.stop)

    def tearDown(self):
        clear_forgot_password_rate_limits()

    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.password_reset_repository.get_latest_reset_token_by_user_id")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_1_first_request_succeeds_returns_200_generic_message(
        self, mock_get_user, mock_get_token, mock_insert_token
    ):
        mock_get_user.return_value = self.mock_user
        mock_get_token.return_value = None

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "developer@ictu.edu.vn"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["message"], PUBLIC_FORGOT_PASSWORD_MESSAGE)
        mock_insert_token.assert_called_once()
        self.mock_send_email.assert_called_once()

    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.password_reset_repository.get_recent_reset_tokens_count")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_2_immediate_subsequent_request_blocked_with_429_and_cooldown(
        self, mock_get_user, mock_get_count, mock_insert_token
    ):
        mock_get_user.return_value = self.mock_user
        mock_get_count.return_value = 0

        # Yêu cầu 1: Thành công
        res1 = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "developer@ictu.edu.vn"},
        )
        self.assertEqual(res1.status_code, 200)

        # Yêu cầu 2 ngay lập tức: Vẫn thành công
        res2 = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "developer@ictu.edu.vn"},
        )
        self.assertEqual(res2.status_code, 200)
        
        # Yêu cầu 3 ngay lập tức: Thành công nhưng kèm retry_after
        res3 = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "developer@ictu.edu.vn"},
        )
        self.assertEqual(res3.status_code, 200)
        self.assertIn("retry_after_seconds", res3.get_json())
        self.assertEqual(res3.get_json()["retry_after_seconds"], 30)

        # Yêu cầu 4 ngay lập tức: Phải bị 429 Too Many Requests
        res4 = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "developer@ictu.edu.vn"},
        )
        self.assertEqual(res4.status_code, 429)
        data4 = res4.get_json()
        self.assertEqual(data4["code"], "FORGOT_PASSWORD_COOLDOWN")
        self.assertEqual(data4["message"], FORGOT_PASSWORD_COOLDOWN_MESSAGE)
        self.assertIn("retry_after_seconds", data4)
        self.assertGreaterEqual(data4["retry_after_seconds"], 1)
        self.assertLessEqual(data4["retry_after_seconds"], FORGOT_PASSWORD_COOLDOWN_SECONDS)
        self.assertEqual(res4.headers.get("Retry-After"), str(data4["retry_after_seconds"]))

        self.assertEqual(mock_insert_token.call_count, 3)
        self.assertEqual(self.mock_send_email.call_count, 3)

    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.password_reset_repository.get_recent_reset_tokens_count")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_3_request_allowed_after_cooldown_expires(
        self, mock_get_user, mock_get_count, mock_insert_token
    ):
        mock_get_user.return_value = self.mock_user
        mock_get_count.return_value = 0

        t0 = datetime(2026, 10, 3, 10, 0, 0, tzinfo=timezone.utc)
        result1 = process_forgot_password_request("developer@ictu.edu.vn", current_time=t0)
        self.assertEqual(result1["message"], PUBLIC_FORGOT_PASSWORD_MESSAGE)

        # 61 giây sau: Cooldown đã hết
        t1 = t0 + timedelta(seconds=61)
        result2 = process_forgot_password_request("developer@ictu.edu.vn", current_time=t1)
        self.assertEqual(result2["message"], PUBLIC_FORGOT_PASSWORD_MESSAGE)

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_4_anti_enumeration_non_existing_email_also_rate_limited(self, mock_get_user):
        mock_get_user.return_value = None

        # Yêu cầu 1 với email không tồn tại: 200 generic message
        res1 = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "nonexistent@ictu.edu.vn"},
        )
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.get_json()["message"], PUBLIC_FORGOT_PASSWORD_MESSAGE)

        # Yêu cầu 2 và 3 với email không tồn tại: 200
        res2 = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "nonexistent@ictu.edu.vn"},
        )
        res3 = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "nonexistent@ictu.edu.vn"},
        )
        self.assertEqual(res3.status_code, 200)

        # Yêu cầu 4 ngay lập tức với cùng email không tồn tại: Trả 429 cooldown
        res4 = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "nonexistent@ictu.edu.vn"},
        )
        self.assertEqual(res4.status_code, 429)
        data4 = res4.get_json()
        self.assertEqual(data4["code"], "FORGOT_PASSWORD_COOLDOWN")
        self.assertEqual(data4["message"], FORGOT_PASSWORD_COOLDOWN_MESSAGE)
        self.assertIn("retry_after_seconds", data4)

    @patch("app.services.auth_service.password_reset_repository.get_recent_reset_tokens_count")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_5_f5_reload_bypass_prevented_by_database_persistent_token(
        self, mock_get_user, mock_get_count
    ):
        """Giả lập trường hợp bộ nhớ bị xóa (reload app / restart worker / F5), token trong DB vẫn kích hoạt rate limit."""
        mock_get_user.return_value = self.mock_user

        # Giả lập DB trả về đã có 3 yêu cầu trong 30s qua
        mock_get_count.return_value = 3

        # Xóa sạch rate limit bộ nhớ để giả lập bypass bộ nhớ
        clear_forgot_password_rate_limits()

        res = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "developer@ictu.edu.vn"},
        )
        self.assertEqual(res.status_code, 429)
        data = res.get_json()
        self.assertEqual(data["code"], "FORGOT_PASSWORD_COOLDOWN")
        # 30 giây cooldown
        self.assertGreaterEqual(data["retry_after_seconds"], 25)
        self.assertLessEqual(data["retry_after_seconds"], 35)

    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    def test_6_reset_token_remains_30_minutes_expiry_and_single_use(self, mock_insert_token):
        fixed_time = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)
        raw_token, record = create_password_reset_token(
            user_id="user-999",
            current_time=fixed_time,
        )

        self.assertEqual(record.created_at, fixed_time)
        self.assertEqual(record.expires_at, fixed_time + timedelta(minutes=30))
        self.assertEqual(record.expires_at - record.created_at, RESET_TOKEN_DURATION)
        self.assertFalse(record.is_used)
        self.assertFalse(record.is_expired(current_time=fixed_time + timedelta(minutes=29)))
        self.assertTrue(record.is_expired(current_time=fixed_time + timedelta(minutes=30, seconds=1)))


if __name__ == "__main__":
    unittest.main()
