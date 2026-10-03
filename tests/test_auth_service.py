import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from werkzeug.security import generate_password_hash

from flask import Flask
from flask_jwt_extended import JWTManager

from app.models.login_session import LoginSession
from app.models.user import User
from app.services.auth_service import (
    AuthValidationError,
    authenticate_and_login,
    validate_credentials,
    verify_password,
)


class AuthServiceTests(unittest.TestCase):
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

        self.user = User(
            id="user-456",
            email="trainer@example.com",
            password_hash=generate_password_hash("ValidPass123!"),
            role="trainer",
            status="active",
        )

        now = datetime.now(timezone.utc)
        self.session = LoginSession(
            session_id="session-456",
            user_id="user-456",
            refresh_jti="jti-456",
            created_at=now,
            last_activity_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=8),
        )
        self.tokens = {
            "access_token": "acc-token",
            "refresh_token": "ref-token",
        }

        # Mock các hàm thao tác database để không kết nối MySQL trong unit test
        self.patch_update_lockout = patch("app.services.auth_service.user_repository.update_user_lockout")
        self.patch_reset_lockout = patch("app.services.auth_service.user_repository.reset_user_lockout")
        self.mock_update_lockout = self.patch_update_lockout.start()
        self.mock_reset_lockout = self.patch_reset_lockout.start()
        self.addCleanup(self.patch_update_lockout.stop)
        self.addCleanup(self.patch_reset_lockout.stop)

    def test_verify_password(self):
        hashed = generate_password_hash("MySecret123")
        self.assertTrue(verify_password(hashed, "MySecret123"))
        self.assertFalse(verify_password(hashed, "WrongSecret"))
        self.assertFalse(verify_password(hashed, ""))
        self.assertFalse(verify_password("", "MySecret123"))
        # Kiểm tra không cho phép so sánh plaintext password
        self.assertFalse(verify_password("MySecret123", "MySecret123"))
        self.assertFalse(verify_password(None, "MySecret123"))
        self.assertFalse(verify_password(hashed, None))

    def test_user_model_check_password(self):
        self.assertTrue(self.user.check_password("ValidPass123!"))
        self.assertFalse(self.user.check_password("WrongSecret"))
        self.assertFalse(self.user.check_password(""))
        plaintext_user = User(
            id="plain-1",
            email="plain@example.com",
            password_hash="PlainPassword123!",
        )
        self.assertFalse(plaintext_user.check_password("PlainPassword123!"))

    def test_user_is_locked(self):
        now = datetime.now(timezone.utc)
        user_unlocked = User(
            id="u1",
            email="u1@example.com",
            password_hash="hash",
            locked_until=None,
        )
        self.assertFalse(user_unlocked.is_locked(current_time=now))

        user_locked_future = User(
            id="u2",
            email="u2@example.com",
            password_hash="hash",
            locked_until=now + timedelta(minutes=10),
        )
        self.assertTrue(user_locked_future.is_locked(current_time=now))

        user_lockout_expired = User(
            id="u3",
            email="u3@example.com",
            password_hash="hash",
            locked_until=now - timedelta(minutes=1),
        )
        self.assertFalse(user_lockout_expired.is_locked(current_time=now))


    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_validate_credentials_success(self, mock_get_user):
        """Kiểm tra: email đúng + password đúng -> trả về User hợp lệ."""
        mock_get_user.return_value = self.user

        user = validate_credentials("trainer@example.com", "ValidPass123!")

        self.assertEqual(user.id, "user-456")
        self.assertEqual(user.email, "trainer@example.com")
        mock_get_user.assert_called_once_with("trainer@example.com")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_validate_credentials_email_not_found(self, mock_get_user):
        """Kiểm tra: email không tồn tại -> báo lỗi INVALID_CREDENTIALS cùng thông báo chung."""
        mock_get_user.return_value = None

        with self.assertRaises(AuthValidationError) as ctx:
            validate_credentials("nonexistent@example.com", "ValidPass123!")

        self.assertEqual(ctx.exception.code, "INVALID_CREDENTIALS")
        self.assertEqual(ctx.exception.message, "Email hoặc mật khẩu không đúng")
        mock_get_user.assert_called_once_with("nonexistent@example.com")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_validate_credentials_wrong_password(self, mock_get_user):
        """Kiểm tra: password sai -> báo lỗi INVALID_CREDENTIALS cùng thông báo chung."""
        mock_get_user.return_value = self.user

        with self.assertRaises(AuthValidationError) as ctx:
            validate_credentials("trainer@example.com", "IncorrectPass!")

        self.assertEqual(ctx.exception.code, "INVALID_CREDENTIALS")
        self.assertEqual(ctx.exception.message, "Email hoặc mật khẩu không đúng")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_invalid_credentials_returns_same_generic_message_and_code(self, mock_get_user):
        """Xác nhận hai trường hợp (email không tồn tại & password sai) trả cùng code và message chung."""
        # 1. Email không tồn tại
        mock_get_user.return_value = None
        with self.assertRaises(AuthValidationError) as ctx_email:
            validate_credentials("nonexistent@example.com", "ValidPass123!")

        # 2. Password sai
        mock_get_user.return_value = self.user
        with self.assertRaises(AuthValidationError) as ctx_pass:
            validate_credentials("trainer@example.com", "WrongPassword123!")

        self.assertEqual(ctx_email.exception.code, ctx_pass.exception.code)
        self.assertEqual(ctx_email.exception.code, "INVALID_CREDENTIALS")
        self.assertEqual(ctx_email.exception.message, ctx_pass.exception.message)
        self.assertEqual(ctx_email.exception.message, "Email hoặc mật khẩu không đúng")

        for msg in (ctx_email.exception.message.lower(), ctx_pass.exception.message.lower()):
            self.assertNotIn("user not found", msg)
            self.assertNotIn("email does not exist", msg)
            self.assertNotIn("password incorrect", msg)


    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_validate_credentials_rejects_plaintext_password(self, mock_get_user):
        """Kiểm tra: không xác thực mật khẩu plaintext lưu trong DB."""
        plaintext_user = User(
            id="user-999",
            email="trainer@example.com",
            password_hash="PlainPass123!",
            role="trainer",
            status="active",
        )
        mock_get_user.return_value = plaintext_user

        with self.assertRaises(AuthValidationError) as ctx:
            validate_credentials("trainer@example.com", "PlainPass123!")

        self.assertEqual(ctx.exception.code, "INVALID_CREDENTIALS")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_validate_credentials_trims_email_whitespace(self, mock_get_user):
        """Kiểm tra: email có khoảng trắng đầu/cuối được xử lý đúng."""
        mock_get_user.return_value = self.user

        user = validate_credentials("   trainer@example.com   ", "ValidPass123!")

        self.assertEqual(user.id, "user-456")
        mock_get_user.assert_called_once_with("trainer@example.com")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_validate_credentials_inactive_account(self, mock_get_user):
        inactive_user = User(
            id="user-789",
            email="disabled@example.com",
            password_hash=generate_password_hash("ValidPass123!"),
            role="trainee",
            status="inactive",
        )
        mock_get_user.return_value = inactive_user

        with self.assertRaises(AuthValidationError) as ctx:
            validate_credentials("disabled@example.com", "ValidPass123!")

        self.assertEqual(ctx.exception.code, "ACCOUNT_INACTIVE")
        self.assertEqual(ctx.exception.message, "Tài khoản hiện không hoạt động. Vui lòng liên hệ quản trị viên.")

    def test_validate_credentials_empty_inputs(self):
        with self.assertRaises(AuthValidationError) as ctx:
            validate_credentials("", "ValidPass123!")
        self.assertEqual(ctx.exception.code, "EMAIL_REQUIRED")

        with self.assertRaises(AuthValidationError) as ctx:
            validate_credentials("trainer@example.com", "")
        self.assertEqual(ctx.exception.code, "PASSWORD_REQUIRED")

    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_authenticate_and_login_success(self, mock_get_user, mock_create_session):
        mock_get_user.return_value = self.user
        mock_create_session.return_value = (self.session, self.tokens)

        with self.app.app_context():
            user, session, tokens = authenticate_and_login("trainer@example.com", "ValidPass123!")

        self.assertEqual(user.id, "user-456")
        self.assertEqual(session.session_id, "session-456")
        self.assertEqual(tokens["access_token"], "acc-token")
        mock_get_user.assert_called_once_with("trainer@example.com")
        mock_create_session.assert_called_once_with(user_id="user-456", roles=["trainer"])

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_authenticate_user_not_found(self, mock_get_user):
        mock_get_user.return_value = None

        with self.assertRaises(AuthValidationError) as ctx:
            authenticate_and_login("notfound@example.com", "ValidPass123!")

        self.assertEqual(ctx.exception.code, "INVALID_CREDENTIALS")
        self.assertEqual(ctx.exception.message, "Email hoặc mật khẩu không đúng")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_authenticate_wrong_password(self, mock_get_user):
        mock_get_user.return_value = self.user

        with self.assertRaises(AuthValidationError) as ctx:
            authenticate_and_login("trainer@example.com", "IncorrectPass!")

        self.assertEqual(ctx.exception.code, "INVALID_CREDENTIALS")
        self.assertEqual(ctx.exception.message, "Email hoặc mật khẩu không đúng")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_authenticate_inactive_account(self, mock_get_user):
        inactive_user = User(
            id="user-789",
            email="disabled@example.com",
            password_hash=generate_password_hash("ValidPass123!"),
            role="trainee",
            status="inactive",
        )
        mock_get_user.return_value = inactive_user

        with self.assertRaises(AuthValidationError) as ctx:
            authenticate_and_login("disabled@example.com", "ValidPass123!")

        self.assertEqual(ctx.exception.code, "ACCOUNT_INACTIVE")
        self.assertEqual(ctx.exception.message, "Tài khoản hiện không hoạt động. Vui lòng liên hệ quản trị viên.")

    def test_authenticate_empty_inputs(self):
        with self.assertRaises(AuthValidationError) as ctx:
            authenticate_and_login("", "ValidPass123!")
        self.assertEqual(ctx.exception.code, "EMAIL_REQUIRED")

        with self.assertRaises(AuthValidationError) as ctx:
            authenticate_and_login("trainer@example.com", "")
        self.assertEqual(ctx.exception.code, "PASSWORD_REQUIRED")

    # =========================================================================
    # SCRUM-34 Tests: Khóa tạm 15 phút sau 5 lần đăng nhập sai
    # =========================================================================

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_failed_attempts_1_to_4_increment_counter(self, mock_get_user):
        """Sai lần 1-4: tăng bộ đếm và trả lỗi INVALID_CREDENTIALS."""
        # Trường hợp 1: Chưa sai lần nào (0) -> sai lần 1
        self.user.failed_login_attempts = 0
        self.user.locked_until = None
        mock_get_user.return_value = self.user

        with self.assertRaises(AuthValidationError) as ctx:
            validate_credentials("trainer@example.com", "WrongPass1")

        self.assertEqual(ctx.exception.code, "INVALID_CREDENTIALS")
        self.assertEqual(self.user.failed_login_attempts, 1)
        self.assertIsNone(self.user.locked_until)
        self.mock_update_lockout.assert_called_with(
            user_id="user-456",
            failed_login_attempts=1,
            locked_until=None,
        )

        # Trường hợp 2: Đã sai 3 lần -> sai lần 4
        self.user.failed_login_attempts = 3
        with self.assertRaises(AuthValidationError) as ctx:
            validate_credentials("trainer@example.com", "WrongPass4")

        self.assertEqual(ctx.exception.code, "INVALID_CREDENTIALS")
        self.assertEqual(self.user.failed_login_attempts, 4)
        self.assertIsNone(self.user.locked_until)
        self.mock_update_lockout.assert_called_with(
            user_id="user-456",
            failed_login_attempts=4,
            locked_until=None,
        )

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_fifth_failed_attempt_locks_account_for_15_minutes(self, mock_get_user):
        """Sai lần 5: khóa tạm 15 phút và trả lỗi ACCOUNT_LOCKED."""
        now = datetime(2026, 9, 30, 10, 0, 0, tzinfo=timezone.utc)
        self.user.failed_login_attempts = 4
        self.user.locked_until = None
        mock_get_user.return_value = self.user

        with self.assertRaises(AuthValidationError) as ctx:
            validate_credentials(
                "trainer@example.com",
                "WrongPass5",
                current_time=now,
            )

        self.assertIn(ctx.exception.code, ("ACCOUNT_TEMP_LOCKED", "ACCOUNT_LOCKED"))
        self.assertEqual(self.user.failed_login_attempts, 5)
        self.assertIsNotNone(self.user.locked_until)
        expected_lock_until = now + timedelta(minutes=15)
        self.assertEqual(self.user.locked_until, expected_lock_until)
        self.assertEqual(ctx.exception.locked_until, expected_lock_until)

        self.mock_update_lockout.assert_called_with(
            user_id="user-456",
            failed_login_attempts=5,
            locked_until=expected_lock_until,
        )

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_login_rejected_during_lockout_period(self, mock_get_user):
        """Trong thời gian khóa: từ chối đăng nhập (cả với mật khẩu đúng và sai)."""
        now = datetime(2026, 9, 30, 10, 5, 0, tzinfo=timezone.utc)
        # Khóa tới 10:15 (còn 10 phút nữa)
        self.user.failed_login_attempts = 5
        self.user.locked_until = datetime(2026, 9, 30, 10, 15, 0, tzinfo=timezone.utc)
        mock_get_user.return_value = self.user

        # Thử với mật khẩu đúng -> vẫn bị từ chối
        with self.assertRaises(AuthValidationError) as ctx_correct:
            validate_credentials(
                "trainer@example.com",
                "ValidPass123!",
                current_time=now,
            )
        self.assertIn(ctx_correct.exception.code, ("ACCOUNT_TEMP_LOCKED", "ACCOUNT_LOCKED"))

        # Thử với mật khẩu sai -> vẫn bị từ chối
        with self.assertRaises(AuthValidationError) as ctx_wrong:
            validate_credentials(
                "trainer@example.com",
                "AnyWrongPassword",
                current_time=now,
            )
        self.assertIn(ctx_wrong.exception.code, ("ACCOUNT_TEMP_LOCKED", "ACCOUNT_LOCKED"))

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_login_allowed_after_15_minutes_expired_success(self, mock_get_user):
        """Hết 15 phút: cho phép đăng nhập lại thành công khi nhập đúng mật khẩu."""
        now = datetime(2026, 9, 30, 10, 20, 0, tzinfo=timezone.utc)
        # Khóa đã hết hạn lúc 10:15
        self.user.failed_login_attempts = 5
        self.user.locked_until = datetime(2026, 9, 30, 10, 15, 0, tzinfo=timezone.utc)
        mock_get_user.return_value = self.user

        user = validate_credentials(
            "trainer@example.com",
            "ValidPass123!",
            current_time=now,
        )

        self.assertEqual(user.id, "user-456")
        self.assertEqual(user.failed_login_attempts, 0)
        self.assertIsNone(user.locked_until)
        self.mock_reset_lockout.assert_called_once_with(user_id="user-456")

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_login_allowed_after_15_minutes_expired_wrong_password_starts_new_count(self, mock_get_user):
        """Hết 15 phút: đăng nhập lại nhưng sai mật khẩu thì bắt đầu chu kỳ đếm mới (1 lần sai)."""
        now = datetime(2026, 9, 30, 10, 20, 0, tzinfo=timezone.utc)
        # Khóa đã hết hạn lúc 10:15
        self.user.failed_login_attempts = 5
        self.user.locked_until = datetime(2026, 9, 30, 10, 15, 0, tzinfo=timezone.utc)
        mock_get_user.return_value = self.user

        with self.assertRaises(AuthValidationError) as ctx:
            validate_credentials(
                "trainer@example.com",
                "WrongPasswordAgain!",
                current_time=now,
            )

        self.assertEqual(ctx.exception.code, "INVALID_CREDENTIALS")
        self.assertEqual(self.user.failed_login_attempts, 1)
        self.assertIsNone(self.user.locked_until)
        self.mock_update_lockout.assert_called_with(
            user_id="user-456",
            failed_login_attempts=1,
            locked_until=None,
        )

    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_successful_login_resets_failed_attempts(self, mock_get_user):
        """Đăng nhập thành công: reset số lần sai."""
        self.user.failed_login_attempts = 3
        self.user.locked_until = None
        mock_get_user.return_value = self.user

        user = validate_credentials("trainer@example.com", "ValidPass123!")

        self.assertEqual(user.id, "user-456")
        self.assertEqual(user.failed_login_attempts, 0)
        self.assertIsNone(user.locked_until)
        self.mock_reset_lockout.assert_called_once_with(user_id="user-456")


if __name__ == "__main__":
    unittest.main()


