import unittest
from unittest.mock import MagicMock, patch

from app.models.user import User
from app.repositories.user_repository import get_user_by_email, get_user_by_id


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
        }

        user = get_user_by_email("user@example.com")

        self.assertIsNotNone(user)
        self.assertIsInstance(user, User)
        self.assertEqual(user.id, "1")
        self.assertEqual(user.email, "user@example.com")
        self.assertEqual(user.role, "admin")
        self.assertEqual(user.status, "active")

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
        }

        user = get_user_by_id("42")

        self.assertIsNotNone(user)
        self.assertEqual(user.id, "42")
        self.assertEqual(user.email, "iduser@example.com")

    @patch("app.repositories.user_repository.get_db_connection")
    def test_get_user_by_id_not_found(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = None

        user = get_user_by_id("999")
        self.assertIsNone(user)


if __name__ == "__main__":
    unittest.main()
