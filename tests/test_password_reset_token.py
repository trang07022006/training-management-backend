from datetime import datetime, timedelta, timezone
import hashlib
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask
from mysql.connector import Error as MySQLError

from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.repositories import password_reset_repository
from app.routes.auth_routes import auth_bp
from app.services.auth_service import (
    PUBLIC_FORGOT_PASSWORD_MESSAGE,
    RESET_TOKEN_DURATION,
    create_password_reset_token,
    generate_reset_token,
    hash_reset_token,
    process_forgot_password_request,
)


class Scrum46PasswordResetTokenTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True)
        self.app.register_blueprint(auth_bp)
        self.client = self.app.test_client()

        self.mock_user = User(
            id="user-ictu-12345",
            email="giangvien@ictu.edu.vn",
            password_hash="pbkdf2:sha256:...",
            role="lecturer",
            status="active",
        )

    # =========================================================================
    # 1. Email tồn tại tạo token
    # =========================================================================
    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_existing_email_creates_and_persists_reset_token(
        self, mock_get_user, mock_insert_token
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

        # Kiểm tra token đã được tạo và lưu vào database
        mock_insert_token.assert_called_once()
        saved_token: PasswordResetToken = mock_insert_token.call_args[0][0]

        self.assertIsInstance(saved_token, PasswordResetToken)
        self.assertEqual(saved_token.user_id, self.mock_user.id)
        self.assertIsNotNone(saved_token.token_hash)
        self.assertEqual(len(saved_token.token_hash), 64)  # SHA-256 hex string dài 64 ký tự

    # =========================================================================
    # 2. Token mỗi lần phải khác nhau (Cryptographic Randomness)
    # =========================================================================
    def test_tokens_are_unique_cryptographic_random(self):
        token_count = 100
        raw_tokens = [generate_reset_token() for _ in range(token_count)]
        token_hashes = [hash_reset_token(t) for t in raw_tokens]

        # Đảm bảo 100 token sinh ra là hoàn toàn phân biệt
        self.assertEqual(len(set(raw_tokens)), token_count)
        # Đảm bảo 100 hash tương ứng cũng hoàn toàn phân biệt
        self.assertEqual(len(set(token_hashes)), token_count)

        for token in raw_tokens:
            self.assertGreaterEqual(len(token), 32)

    # =========================================================================
    # 3. Expiry khoảng 30 phút
    # =========================================================================
    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    def test_token_expiration_is_exactly_30_minutes(self, mock_insert_token):
        fixed_now = datetime(2026, 9, 30, 15, 0, 0, tzinfo=timezone.utc)
        raw_token, token_record = create_password_reset_token(
            user_id="user-999",
            current_time=fixed_now,
        )

        expected_expiry = fixed_now + timedelta(minutes=30)
        self.assertEqual(token_record.created_at, fixed_now)
        self.assertEqual(token_record.expires_at, expected_expiry)
        self.assertEqual(
            token_record.expires_at - token_record.created_at,
            timedelta(minutes=30),
        )

        # Kiểm tra phương thức is_expired:
        # Thời điểm 29 phút 59 giây -> chưa hết hạn
        at_29_min = fixed_now + timedelta(minutes=29, seconds=59)
        self.assertFalse(token_record.is_expired(current_time=at_29_min))

        # Thời điểm 30 phút 0 giây -> đã hết hạn
        at_30_min = fixed_now + timedelta(minutes=30)
        self.assertTrue(token_record.is_expired(current_time=at_30_min))

        # Thời điểm 31 phút -> đã hết hạn
        at_31_min = fixed_now + timedelta(minutes=31)
        self.assertTrue(token_record.is_expired(current_time=at_31_min))

    # =========================================================================
    # 4. Token lưu đúng persistence (Repository Tests)
    # =========================================================================
    @patch("app.repositories.password_reset_repository.get_db_connection")
    def test_repository_insert_reset_token(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        token = PasswordResetToken(
            id="token-uuid-123",
            user_id="user-456",
            token_hash="a" * 64,
            created_at=datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc),
            expires_at=datetime(2026, 9, 30, 12, 30, 0, tzinfo=timezone.utc),
        )

        password_reset_repository.insert_reset_token(token)

        # Kiểm tra đã gọi execute với đúng câu lệnh INSERT và tham số
        mock_cursor.execute.assert_called_once()
        sql, params = mock_cursor.execute.call_args[0]
        self.assertIn("INSERT INTO password_reset_tokens", sql)
        self.assertEqual(params[0], "token-uuid-123")
        self.assertEqual(params[1], "user-456")
        self.assertEqual(params[2], "a" * 64)
        # Kiểm tra transaction commit
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("app.repositories.password_reset_repository.get_db_connection")
    def test_repository_get_reset_token_by_hash(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {
            "id": "token-1",
            "user_id": "user-1",
            "token_hash": "sample_hash_64_chars" + "0" * 44,
            "created_at": datetime(2026, 9, 30, 14, 0, 0),
            "expires_at": datetime(2026, 9, 30, 14, 30, 0),
        }

        found_token = password_reset_repository.get_reset_token_by_hash(
            "sample_hash_64_chars" + "0" * 44
        )

        self.assertIsNotNone(found_token)
        self.assertEqual(found_token.id, "token-1")
        self.assertEqual(found_token.user_id, "user-1")
        self.assertEqual(found_token.created_at.tzinfo, timezone.utc)
        self.assertEqual(found_token.expires_at.tzinfo, timezone.utc)

    # =========================================================================
    # 5. Email không tồn tại không tạo token
    # =========================================================================
    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_non_existing_email_does_not_create_token(
        self, mock_get_user, mock_insert_token
    ):
        mock_get_user.return_value = None

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "nonexistent@ictu.edu.vn"},
        )

        self.assertEqual(response.status_code, 200)
        # Tuyệt đối không tạo reset token khi tài khoản không tồn tại
        mock_insert_token.assert_not_called()

    # =========================================================================
    # 6. Public response không lộ token (Anti-enumeration & Bảo mật)
    # =========================================================================
    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_public_response_never_leaks_token_or_details(
        self, mock_get_user, mock_insert_token
    ):
        mock_get_user.return_value = self.mock_user

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "giangvien@ictu.edu.vn"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        # Response chỉ chứa trường 'message'
        self.assertEqual(list(data.keys()), ["message"])
        self.assertEqual(data["message"], PUBLIC_FORGOT_PASSWORD_MESSAGE)

        raw_response_text = response.get_data(as_text=True)
        # Đảm bảo không lộ token, token_hash hay user_id ra response
        self.assertNotIn("token", raw_response_text.lower().replace("đặt lại mật khẩu", ""))
        self.assertNotIn(self.mock_user.id, raw_response_text)

    # =========================================================================
    # 7. Lỗi database không fallback mock
    # =========================================================================
    @patch("app.services.auth_service.password_reset_repository.insert_reset_token")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_database_error_on_insert_returns_500_without_mock_fallback(
        self, mock_get_user, mock_insert_token
    ):
        mock_get_user.return_value = self.mock_user
        mock_insert_token.side_effect = MySQLError("Database disk full or constraint error")

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "giangvien@ictu.edu.vn"},
        )

        # Phải trả về status 500, KHÔNG fallback mock 200
        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertEqual(data["code"], "DATABASE_ERROR")
        self.assertNotIn(PUBLIC_FORGOT_PASSWORD_MESSAGE, str(data))


if __name__ == "__main__":
    unittest.main()
