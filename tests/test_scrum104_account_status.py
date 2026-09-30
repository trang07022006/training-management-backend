import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models.user import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_INACTIVE,
    ACCOUNT_STATUS_LOCKED,
    User,
)
from app.services.user_service import (
    UserNotFoundError,
    get_user_account_status,
)


class Scrum104AccountStatusTests(unittest.TestCase):
    """
    Kiểm thử SCRUM-104: Chuẩn hóa xử lý trạng thái khóa tài khoản người dùng.
    1. Active user -> status active, is_locked=False, is_active=True
    2. Locked user (admin locked) -> status locked, is_locked=True, is_active=False
    3. Temporarily locked user (failed logins) -> is_locked=True
    4. Unknown status -> fallback an toàn dạng "unknown", không gây sập hệ thống
    5. User not found -> UserNotFoundError
    6. Response tuyệt đối không leak DB internals hay password hash
    """

    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.active_user = User(
            id="user-active-104",
            email="active@tms.local",
            password_hash="$2b$12$somehashedpasswordstring12345",
            name="Active User",
            status=ACCOUNT_STATUS_ACTIVE,
            failed_login_attempts=0,
            locked_until=None,
        )

        self.locked_user = User(
            id="user-locked-104",
            email="locked@tms.local",
            password_hash="$2b$12$anotherhashedpasswordstring67890",
            name="Locked User",
            status=ACCOUNT_STATUS_LOCKED,
            failed_login_attempts=0,
            locked_until=None,
        )

        self.temp_locked_user = User(
            id="user-templocked-104",
            email="templocked@tms.local",
            password_hash="$2b$12$tempsecretpasswordsaltvalue",
            name="Temp Locked User",
            status=ACCOUNT_STATUS_ACTIVE,
            failed_login_attempts=5,
            locked_until=self.now + timedelta(minutes=15),
        )

    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_01_active_user_status(self, mock_get_user):
        """1. Đọc trạng thái tài khoản đang hoạt động bình thường."""
        mock_get_user.return_value = self.active_user
        res = get_user_account_status("user-active-104")

        self.assertEqual(res["user_id"], "user-active-104")
        self.assertEqual(res["status"], ACCOUNT_STATUS_ACTIVE)
        self.assertFalse(res["is_locked"])
        self.assertTrue(res["is_active"])
        self.assertTrue(self.active_user.is_active())
        self.assertFalse(self.active_user.is_account_locked())

    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_02_locked_user_status(self, mock_get_user):
        """2. Đọc trạng thái tài khoản bị khóa bởi quản trị viên."""
        mock_get_user.return_value = self.locked_user
        res = get_user_account_status("user-locked-104")

        self.assertEqual(res["user_id"], "user-locked-104")
        self.assertEqual(res["status"], ACCOUNT_STATUS_LOCKED)
        self.assertTrue(res["is_locked"])
        self.assertFalse(res["is_active"])
        self.assertTrue(self.locked_user.is_account_locked())
        self.assertFalse(self.locked_user.is_active())

    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_03_temporarily_locked_user_status(self, mock_get_user):
        """3. Tài khoản bị khóa tạm thời do sai mật khẩu."""
        mock_get_user.return_value = self.temp_locked_user
        res = get_user_account_status("user-templocked-104")

        self.assertTrue(res["is_locked"])
        self.assertFalse(res["is_active"])
        self.assertTrue(self.temp_locked_user.is_account_locked(current_time=self.now))

    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_04_unknown_status_fallback_safe(self, mock_get_user):
        """4. Trạng thái không xác định trong DB được xử lý an toàn (fallback unknown)."""
        weird_user = User(
            id="user-weird-104",
            email="weird@tms.local",
            password_hash="hash",
            status="corrupted_or_custom",
        )
        mock_get_user.return_value = weird_user
        res = get_user_account_status("user-weird-104")

        self.assertEqual(res["status"], "unknown")
        self.assertFalse(res["is_active"])

    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_05_user_not_found_raises_error(self, mock_get_user):
        """5. Không tìm thấy người dùng -> ném UserNotFoundError."""
        mock_get_user.return_value = None
        with self.assertRaises(UserNotFoundError):
            get_user_account_status("nonexistent-104")

    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_06_no_sensitive_data_exposure(self, mock_get_user):
        """6. Dữ liệu trạng thái tuyệt đối không làm lộ password_hash hay DB internals."""
        mock_get_user.return_value = self.active_user
        res = get_user_account_status("user-active-104")

        self.assertNotIn("password_hash", res)
        self.assertNotIn("password", res)
        self.assertNotIn("salt", res)
        for key, val in res.items():
            self.assertNotEqual(val, "$2b$12$somehashedpasswordstring12345")


if __name__ == "__main__":
    unittest.main()
