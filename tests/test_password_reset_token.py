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
    AuthValidationError,
    PUBLIC_FORGOT_PASSWORD_MESSAGE,
    RESET_TOKEN_DURATION,
    create_password_reset_token,
    generate_reset_token,
    hash_reset_token,
    process_forgot_password_request,
    reset_password_with_token,
    validate_reset_token,
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

        self.patch_send_email = patch(
            "app.services.auth_service.email_service.send_password_reset_email"
        )
        self.mock_send_email = self.patch_send_email.start()
        self.addCleanup(self.patch_send_email.stop)

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


class Scrum47SingleUsePasswordResetTokenTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True)
        self.app.register_blueprint(auth_bp)
        self.client = self.app.test_client()

        self.fixed_now = datetime.now(timezone.utc)
        self.raw_token = "secure-random-token-xyz-1234567890"
        self.token_hash = hash_reset_token(self.raw_token)
        self.user_id = "user-ictu-12345"

        self.valid_token = PasswordResetToken(
            id="token-uuid-001",
            user_id=self.user_id,
            token_hash=self.token_hash,
            created_at=self.fixed_now - timedelta(minutes=10),
            expires_at=self.fixed_now + timedelta(minutes=20),
            used_at=None,
        )

    # =========================================================================
    # 1. token hợp lệ được chấp nhận
    # =========================================================================
    @patch("app.repositories.password_reset_repository.get_reset_token_by_hash")
    def test_valid_token_is_accepted(self, mock_get_token):
        mock_get_token.return_value = self.valid_token

        # Test service: validate_reset_token
        result = validate_reset_token(self.raw_token, current_time=self.fixed_now)
        self.assertEqual(result.id, self.valid_token.id)
        self.assertFalse(result.is_used)

        # Test endpoint verify-reset-token
        response = self.client.post(
            "/api/auth/verify-reset-token",
            json={"token": self.raw_token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["valid"])

    # =========================================================================
    # 2. token dùng lần đầu PASS
    # =========================================================================
    @patch("app.repositories.password_reset_repository.execute_reset_password_transaction")
    def test_first_use_of_token_succeeds(self, mock_execute_tx):
        mock_execute_tx.return_value = self.valid_token

        response = self.client.post(
            "/api/auth/reset-password",
            json={
                "token": self.raw_token,
                "new_password": "NewSecretPassword123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("thành công", response.get_json()["message"])
        mock_execute_tx.assert_called_once()
        # Đảm bảo không làm lộ token ra response
        self.assertNotIn(self.raw_token, response.get_data(as_text=True))
        self.assertNotIn(self.token_hash, response.get_data(as_text=True))

    # =========================================================================
    # 3. token dùng lần hai FAIL
    # =========================================================================
    def test_second_use_of_token_fails(self):
        """Mô phỏng chu trình thực tế: lần đầu dùng thành công, lần thứ hai dùng lại cùng token bị từ chối."""
        tokens_db = {
            self.token_hash: {
                "id": "token-uuid-001",
                "user_id": self.user_id,
                "token_hash": self.token_hash,
                "created_at": self.fixed_now - timedelta(minutes=5),
                "expires_at": self.fixed_now + timedelta(minutes=25),
                "used_at": None,
            }
        }
        users_db = {
            self.user_id: {
                "id": self.user_id,
                "password_hash": "old-hash",
            }
        }

        with patch("app.repositories.password_reset_repository.get_db_connection") as mock_conn:
            fake_conn = MagicMock()
            fake_cursor = MagicMock()
            fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
            mock_conn.return_value = fake_conn

            def fake_execute(query, params):
                if "SELECT" in query and "FROM password_reset_tokens" in query:
                    t_hash = params[0]
                    fake_cursor.fetchone.return_value = tokens_db.get(t_hash)
                elif "UPDATE users" in query:
                    new_pw, uid = params
                    users_db[uid]["password_hash"] = new_pw
                    fake_cursor.rowcount = 1
                elif "UPDATE password_reset_tokens" in query:
                    used_at_val, tid = params
                    for t in tokens_db.values():
                        if t["id"] == tid:
                            t["used_at"] = used_at_val

            fake_cursor.execute.side_effect = fake_execute

            # Lần 1: Dùng token lần đầu -> PASS
            res1 = self.client.post(
                "/api/auth/reset-password",
                json={"token": self.raw_token, "new_password": "NewPassword123!"},
            )
            self.assertEqual(res1.status_code, 200)
            self.assertIsNotNone(tokens_db[self.token_hash]["used_at"])

            # Lần 2: Dùng lại đúng token đó -> FAIL (bị từ chối vì đã used)
            res2 = self.client.post(
                "/api/auth/reset-password",
                json={"token": self.raw_token, "new_password": "AnotherPassword456!"},
            )
            self.assertEqual(res2.status_code, 400)
            self.assertEqual(res2.get_json()["code"], "TOKEN_ALREADY_USED")

    # =========================================================================
    # 4. token đã đánh dấu used bị từ chối
    # =========================================================================
    @patch("app.repositories.password_reset_repository.get_reset_token_by_hash")
    def test_already_used_token_is_rejected(self, mock_get_token):
        used_token = PasswordResetToken(
            id="token-used-001",
            user_id=self.user_id,
            token_hash=self.token_hash,
            created_at=self.fixed_now - timedelta(minutes=15),
            expires_at=self.fixed_now + timedelta(minutes=15),
            used_at=self.fixed_now - timedelta(minutes=5),
        )
        mock_get_token.return_value = used_token

        with self.assertRaises(AuthValidationError) as ctx:
            validate_reset_token(self.raw_token, current_time=self.fixed_now)
        self.assertEqual(ctx.exception.code, "TOKEN_ALREADY_USED")

        response = self.client.post(
            "/api/auth/verify-reset-token",
            json={"token": self.raw_token},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "TOKEN_ALREADY_USED")

    # =========================================================================
    # 5. token hết hạn bị từ chối
    # =========================================================================
    @patch("app.repositories.password_reset_repository.get_reset_token_by_hash")
    def test_expired_token_is_rejected(self, mock_get_token):
        expired_token = PasswordResetToken(
            id="token-exp-001",
            user_id=self.user_id,
            token_hash=self.token_hash,
            created_at=self.fixed_now - timedelta(minutes=35),
            expires_at=self.fixed_now - timedelta(minutes=5),
            used_at=None,
        )
        mock_get_token.return_value = expired_token

        with self.assertRaises(AuthValidationError) as ctx:
            validate_reset_token(self.raw_token, current_time=self.fixed_now)
        self.assertEqual(ctx.exception.code, "TOKEN_EXPIRED")

        response = self.client.post(
            "/api/auth/verify-reset-token",
            json={"token": self.raw_token},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "TOKEN_EXPIRED")

    # =========================================================================
    # 6. token không tồn tại bị từ chối
    # =========================================================================
    @patch("app.repositories.password_reset_repository.get_reset_token_by_hash")
    def test_non_existent_token_is_rejected(self, mock_get_token):
        mock_get_token.return_value = None

        with self.assertRaises(AuthValidationError) as ctx:
            validate_reset_token("non-existent-token", current_time=self.fixed_now)
        self.assertEqual(ctx.exception.code, "INVALID_TOKEN")

        response = self.client.post(
            "/api/auth/verify-reset-token",
            json={"token": "non-existent-token"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "INVALID_TOKEN")

    # =========================================================================
    # 7. token hash lookup đúng
    # =========================================================================
    @patch("app.repositories.password_reset_repository.get_reset_token_by_hash")
    def test_token_hash_lookup_uses_sha256(self, mock_get_token):
        mock_get_token.return_value = self.valid_token

        raw_test_token = "special_secret_token_12345"
        expected_hash = hashlib.sha256(raw_test_token.encode("utf-8")).hexdigest()

        validate_reset_token(raw_test_token, current_time=self.fixed_now)

        # Đảm bảo lookup bằng hash SHA-256 64 ký tự, không bao giờ dùng raw token
        mock_get_token.assert_called_once_with(expected_hash)
        self.assertNotEqual(mock_get_token.call_args[0][0], raw_test_token)

    # =========================================================================
    # 8. update password lỗi thì token chưa bị consume
    # =========================================================================
    @patch("app.repositories.password_reset_repository.get_db_connection")
    def test_failed_password_update_does_not_consume_token(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {
            "id": "token-1",
            "user_id": "user-1",
            "token_hash": self.token_hash,
            "created_at": self.fixed_now - timedelta(minutes=5),
            "expires_at": self.fixed_now + timedelta(minutes=25),
            "used_at": None,
        }

        # Giả lập lỗi ở bước update users
        def cursor_execute(sql, params):
            if "UPDATE users" in sql:
                raise MySQLError("Database disk write error during password update")

        mock_cursor.execute.side_effect = cursor_execute

        with self.assertRaises(MySQLError):
            password_reset_repository.execute_reset_password_transaction(
                token_hash=self.token_hash,
                new_password_hash="new-hash",
                current_time=self.fixed_now,
            )

        # Kiểm tra bước UPDATE password_reset_tokens KHÔNG BAO GIỜ được gọi
        called_sqls = [call[0][0] for call in mock_cursor.execute.call_args_list]
        update_token_sqls = [s for s in called_sqls if "UPDATE password_reset_tokens" in s]
        self.assertEqual(len(update_token_sqls), 0)

        # Kiểm tra rollback được gọi
        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    # =========================================================================
    # 9. transaction rollback đúng khi có lỗi
    # =========================================================================
    @patch("app.repositories.password_reset_repository.get_db_connection")
    def test_transaction_rollback_on_any_error(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {
            "id": "token-1",
            "user_id": "user-1",
            "token_hash": self.token_hash,
            "created_at": self.fixed_now - timedelta(minutes=5),
            "expires_at": self.fixed_now + timedelta(minutes=25),
            "used_at": None,
        }

        # Giả lập lỗi ở bước update token used_at
        def cursor_execute(sql, params):
            if "UPDATE password_reset_tokens" in sql:
                raise MySQLError("Deadlock or constraint error during token update")

        mock_cursor.execute.side_effect = cursor_execute

        with self.assertRaises(MySQLError):
            password_reset_repository.execute_reset_password_transaction(
                token_hash=self.token_hash,
                new_password_hash="new-hash",
                current_time=self.fixed_now,
            )

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()
        mock_conn.close.assert_called_once()

    # =========================================================================
    # 10. lỗi database không fallback mock
    # =========================================================================
    @patch("app.services.auth_service.password_reset_repository.execute_reset_password_transaction")
    def test_database_error_on_reset_password_returns_500_without_mock_fallback(
        self, mock_execute_tx
    ):
        mock_execute_tx.side_effect = MySQLError("MySQL connection lost")

        response = self.client.post(
            "/api/auth/reset-password",
            json={
                "token": self.raw_token,
                "new_password": "ValidPassword123!",
            },
        )

        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertEqual(data["code"], "DATABASE_ERROR")
        self.assertNotIn("thành công", str(data))

    # =========================================================================
    # 11. Transaction ordering: validate -> update password -> mark used -> commit
    # =========================================================================
    @patch("app.repositories.password_reset_repository.get_db_connection")
    def test_transaction_execution_strict_order(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {
            "id": "token-1",
            "user_id": "user-1",
            "token_hash": self.token_hash,
            "created_at": self.fixed_now - timedelta(minutes=5),
            "expires_at": self.fixed_now + timedelta(minutes=25),
            "used_at": None,
        }

        call_order = []

        def tracked_execute(sql, params):
            if "SELECT" in sql:
                call_order.append("validate_token")
            elif "UPDATE users" in sql:
                call_order.append("update_password")
            elif "UPDATE password_reset_tokens" in sql:
                call_order.append("mark_token_used")

        mock_cursor.execute.side_effect = tracked_execute
        mock_conn.commit.side_effect = lambda: call_order.append("commit")

        password_reset_repository.execute_reset_password_transaction(
            token_hash=self.token_hash,
            new_password_hash="hashed-pw",
            current_time=self.fixed_now,
        )

        expected_order = [
            "validate_token",
            "update_password",
            "mark_token_used",
            "commit",
        ]
        self.assertEqual(call_order, expected_order)

    # =========================================================================
    # 12. Payload validation: thiếu token hoặc mật khẩu bị từ chối 400
    # =========================================================================
    def test_missing_token_or_password_returns_400(self):
        # Thiếu token
        res1 = self.client.post(
            "/api/auth/reset-password",
            json={"new_password": "ValidPassword123!"},
        )
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json()["code"], "TOKEN_REQUIRED")

        # Thiếu password
        res2 = self.client.post(
            "/api/auth/reset-password",
            json={"token": self.raw_token},
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "PASSWORD_REQUIRED")

        # Non-JSON
        res3 = self.client.post(
            "/api/auth/reset-password",
            data="not json",
        )
        self.assertEqual(res3.status_code, 400)


if __name__ == "__main__":
    unittest.main()
