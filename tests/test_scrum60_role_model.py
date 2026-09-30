import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from mysql.connector import Error as MySQLError, IntegrityError

from app.models.role import Role
from app.repositories import role_repository


class Scrum60RoleModelTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-60: Xây dựng Role Model.
    1. role representation hợp lệ
    2. tìm role theo id
    3. tìm role theo code/name
    4. role không tồn tại
    5. duplicate role được database/service xử lý
    6. database error không fallback mock
    7. query parameterized
    """

    def setUp(self):
        self.role_id = "role-admin-uuid-123"
        self.now = datetime.now(timezone.utc)
        self.role = Role(
            id=self.role_id,
            code="admin",
            name="Quản trị viên",
            description="Toàn quyền quản trị hệ thống",
            created_at=self.now,
            updated_at=self.now,
        )

    # 1. role representation hợp lệ
    def test_01_role_representation_valid(self):
        self.assertEqual(self.role.id, self.role_id)
        self.assertEqual(self.role.code, "admin")
        self.assertEqual(self.role.name, "Quản trị viên")
        self.assertEqual(self.role.description, "Toàn quyền quản trị hệ thống")
        self.assertIsInstance(self.role.created_at, datetime)
        self.assertIsInstance(self.role.updated_at, datetime)

    # 2. tìm role theo id
    @patch("app.repositories.role_repository._database_cursor")
    def test_02_find_role_by_id(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "id": self.role_id,
            "code": "admin",
            "name": "Quản trị viên",
            "description": "Toàn quyền quản trị hệ thống",
            "created_at": self.now,
            "updated_at": self.now,
        }
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        result = role_repository.get_role_by_id(self.role_id)

        self.assertIsNotNone(result)
        self.assertEqual(result.id, self.role_id)
        self.assertEqual(result.code, "admin")
        self.assertEqual(result.name, "Quản trị viên")
        mock_cursor.execute.assert_called_once()
        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("WHERE id = %s", sql)
        self.assertEqual(values, (self.role_id,))

    # 3. tìm role theo code/name
    @patch("app.repositories.role_repository._database_cursor")
    def test_03_find_role_by_code(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "id": self.role_id,
            "code": "trainer",
            "name": "Giảng viên",
            "description": "Đào tạo học viên",
            "created_at": self.now,
            "updated_at": self.now,
        }
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        result = role_repository.get_role_by_code("trainer")

        self.assertIsNotNone(result)
        self.assertEqual(result.code, "trainer")
        self.assertEqual(result.name, "Giảng viên")
        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("WHERE code = %s", sql)
        self.assertEqual(values, ("trainer",))

    # 4. role không tồn tại
    @patch("app.repositories.role_repository._database_cursor")
    def test_04_role_not_found_returns_none(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        result_id = role_repository.get_role_by_id("non-existent-id")
        result_code = role_repository.get_role_by_code("non-existent-code")

        self.assertIsNone(result_id)
        self.assertIsNone(result_code)

    # 5. duplicate role được database/service xử lý (IntegrityError ném ra, không bị nuốt lỗi)
    @patch("app.repositories.role_repository._database_cursor")
    def test_05_duplicate_role_handled(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = IntegrityError("1062 (23000): Duplicate entry 'admin' for key 'code'")
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        with self.assertRaises(IntegrityError):
            role_repository.insert_role(self.role)

    # 6. database error không fallback mock
    @patch("app.repositories.role_repository._database_cursor")
    def test_06_database_error_does_not_fallback_to_mock(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = MySQLError("MySQL Connection timed out")
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        with self.assertRaises(MySQLError):
            role_repository.get_role_by_id(self.role_id)

        with self.assertRaises(MySQLError):
            role_repository.get_all_roles()

    # 7. query parameterized: ngăn ngừa triệt để SQL Injection
    @patch("app.repositories.role_repository._database_cursor")
    def test_07_queries_are_parameterized(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        malicious_input = "' OR '1'='1"
        role_repository.get_role_by_code(malicious_input)

        sql, values = mock_cursor.execute.call_args[0]
        # SQL phải chứa placeholder %s và tham số độc hại được truyền trong tuple values
        self.assertIn("%s", sql)
        self.assertNotIn(malicious_input, sql)
        self.assertEqual(values, (malicious_input,))


if __name__ == "__main__":
    unittest.main()
