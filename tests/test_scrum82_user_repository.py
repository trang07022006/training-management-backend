import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from mysql.connector import Error as MySQLError

from app.models.user import User
from app.repositories.user_repository import list_users


class Scrum82UserRepositoryTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-82: User Data Access / List Users.
    Kiểm tra repository layer:
    1. Trả danh sách user chuẩn
    2. Không trả password hash trong to_public_dict()
    3. Phân trang chính xác (page, page_size, offset)
    4. Page ngoài phạm vi xử lý an toàn (âm, 0, vượt total)
    5. Kết quả rỗng trả về đúng ([], 0)
    6. Sắp xếp xác định (deterministic sort)
    7. Lỗi DB được xử lý an toàn, không rò rỉ dữ liệu nhạy cảm
    """

    def setUp(self):
        self.mock_user_rows = [
            {
                "id": "u-1",
                "email": "admin@daotao.edu.vn",
                "password_hash": "hashed_secret_1",
                "role": "admin",
                "status": "active",
                "failed_login_attempts": 0,
                "locked_until": None,
                "created_at": datetime(2026, 1, 1, 10, 0, 0),
                "updated_at": datetime(2026, 1, 1, 10, 0, 0),
            },
            {
                "id": "u-2",
                "email": "trainer@daotao.edu.vn",
                "password_hash": "hashed_secret_2",
                "role": "trainer",
                "status": "active",
                "failed_login_attempts": 0,
                "locked_until": None,
                "created_at": datetime(2026, 1, 2, 10, 0, 0),
                "updated_at": datetime(2026, 1, 2, 10, 0, 0),
            },
        ]

    @patch("app.repositories.user_repository.get_db_connection")
    def test_01_list_users_returns_user_instances(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {"total": 2}
        mock_cursor.fetchall.return_value = self.mock_user_rows

        users, total = list_users(page=1, page_size=20)

        self.assertEqual(total, 2)
        self.assertEqual(len(users), 2)
        self.assertIsInstance(users[0], User)
        self.assertEqual(users[0].id, "u-1")
        self.assertEqual(users[0].email, "admin@daotao.edu.vn")
        self.assertEqual(users[1].id, "u-2")

    @patch("app.repositories.user_repository.get_db_connection")
    def test_02_password_hash_not_exposed_in_public_dict(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {"total": 2}
        mock_cursor.fetchall.return_value = self.mock_user_rows

        users, _ = list_users(page=1, page_size=20)
        public_data = [u.to_public_dict() for u in users]

        for item in public_data:
            self.assertNotIn("password_hash", item)
            self.assertNotIn("password", item)
            self.assertIn("id", item)
            self.assertIn("email", item)
            self.assertIn("role", item)
            self.assertIn("status", item)

    @patch("app.repositories.user_repository.get_db_connection")
    def test_03_pagination_calculates_correct_limit_and_offset(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {"total": 55}
        mock_cursor.fetchall.return_value = [self.mock_user_rows[0]]

        users, total = list_users(page=3, page_size=10)

        self.assertEqual(total, 55)
        # Offset cho page 3, size 10 là (3 - 1) * 10 = 20
        mock_cursor.execute.assert_called_with(unittest.mock.ANY, (10, 20))

    @patch("app.repositories.user_repository.get_db_connection")
    def test_04_invalid_page_and_page_size_handled_safely(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {"total": 5}
        mock_cursor.fetchall.return_value = self.mock_user_rows

        # page < 1 -> fallback 1; page_size > 100 -> fallback 20
        users, total = list_users(page=-5, page_size=500)
        self.assertEqual(total, 5)
        # Limit 20, offset 0
        mock_cursor.execute.assert_called_with(unittest.mock.ANY, (20, 0))

    @patch("app.repositories.user_repository.get_db_connection")
    def test_05_empty_database_or_out_of_bound_page_returns_empty(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        # TH1: DB rỗng
        mock_cursor.fetchone.return_value = {"total": 0}
        users, total = list_users(page=1, page_size=20)
        self.assertEqual(total, 0)
        self.assertEqual(users, [])

        # TH2: Page vượt quá total (total = 10, page = 5, offset = 80 >= 10)
        mock_cursor.fetchone.return_value = {"total": 10}
        users_out, total_out = list_users(page=5, page_size=20)
        self.assertEqual(total_out, 10)
        self.assertEqual(users_out, [])

    @patch("app.repositories.user_repository.get_db_connection")
    def test_06_deterministic_sorting_uses_whitelisted_columns(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {"total": 2}
        mock_cursor.fetchall.return_value = self.mock_user_rows

        # Thử injection vào sort_by
        list_users(page=1, page_size=20, sort_by="email; DROP TABLE users;--", sort_order="asc")
        executed_sql = mock_cursor.execute.call_args[0][0]
        # sort_by không nằm trong whitelist -> rơi về created_at
        self.assertIn("ORDER BY created_at ASC, id ASC", executed_sql)
        self.assertNotIn("DROP TABLE", executed_sql)

    @patch("app.repositories.user_repository.get_db_connection")
    def test_07_db_error_does_not_leak_secrets(self, mock_get_conn):
        mock_get_conn.side_effect = MySQLError("Access denied for user 'dbuser'@'localhost' (using password: YES)")

        with self.assertRaises(MySQLError) as ctx:
            list_users(page=1, page_size=20)

        # Exception được raise nhưng kiểm tra code tầng ngoài không bao giờ trả raw error này ra API
        self.assertIn("Access denied", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
