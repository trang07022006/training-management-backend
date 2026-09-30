from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock, patch

from app.models.user import User
from app.repositories.user_repository import (
    get_user_by_email,
    get_user_by_id,
    reset_user_lockout,
    update_user_lockout,
)


class UserRepositoryTests(unittest.TestCase):
    @patch("app.repositories.user_repository.get_db_connection")
    def test_get_user_by_email_found(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {
            "id": "1",
            "email": "user@example.com",
            "password_hash": "hashed_pass",
            "role": "admin",
            "status": "active",
            "failed_login_attempts": 2,
            "locked_until": datetime(2026, 9, 30, 10, 0, 0),
        }

        user = get_user_by_email("user@example.com")

        self.assertIsNotNone(user)
        self.assertIsInstance(user, User)
        self.assertEqual(user.id, "1")
        self.assertEqual(user.email, "user@example.com")
        self.assertEqual(user.role, "admin")
        self.assertEqual(user.status, "active")
        self.assertEqual(user.failed_login_attempts, 2)
        self.assertIsNotNone(user.locked_until)
        self.assertEqual(user.locked_until.tzinfo, timezone.utc)

    @patch("app.repositories.user_repository.get_db_connection")
    def test_get_user_by_email_not_found(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = None

        user = get_user_by_email("notfound@example.com")
        self.assertIsNone(user)

    @patch("app.repositories.user_repository.get_db_connection")
    def test_get_user_by_id_found(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {
            "id": "42",
            "email": "iduser@example.com",
            "password_hash": "hash_42",
            "role": "trainee",
            "status": "active",
            "failed_login_attempts": 0,
            "locked_until": None,
        }

        user = get_user_by_id("42")

        self.assertIsNotNone(user)
        self.assertEqual(user.id, "42")
        self.assertEqual(user.email, "iduser@example.com")
        self.assertEqual(user.failed_login_attempts, 0)
        self.assertIsNone(user.locked_until)

    @patch("app.repositories.user_repository.get_db_connection")
    def test_get_user_by_id_not_found(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = None

        user = get_user_by_id("999")
        self.assertIsNone(user)

    @patch("app.repositories.user_repository.get_db_connection")
    def test_update_user_lockout(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        lock_time = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
        update_user_lockout("user-123", 5, lock_time)

        mock_conn.commit.assert_called_once()
        mock_cursor.execute.assert_called_once()
        args, kwargs = mock_cursor.execute.call_args
        self.assertIn("UPDATE users", args[0])
        self.assertEqual(args[1][0], 5)
        self.assertEqual(args[1][2], "user-123")

    @patch("app.repositories.user_repository.get_db_connection")
    def test_reset_user_lockout(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        reset_user_lockout("user-123")

        mock_conn.commit.assert_called_once()
        mock_cursor.execute.assert_called_once()
        args, kwargs = mock_cursor.execute.call_args
        self.assertIn("failed_login_attempts = 0", args[0])
        self.assertEqual(args[1], ("user-123",))


if __name__ == "__main__":
    unittest.main()

