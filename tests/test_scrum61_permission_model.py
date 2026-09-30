import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from mysql.connector import Error as MySQLError, IntegrityError

from app.models.permission import Permission
from app.repositories import permission_repository


class Scrum61PermissionModelTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-61: Xây dựng Permission Model.
    1. tạo/read permission representation
    2. lookup permission theo code
    3. duplicate permission bị xử lý
    4. permission không tồn tại
    5. database error không fallback mock
    6. parameterized SQL
    7. regression role tests PASS
    """

    def setUp(self):
        self.permission_id = "perm-user-view-uuid-123"
        self.now = datetime.now(timezone.utc)
        self.permission = Permission(
            id=self.permission_id,
            code="user.view",
            name="Xem thông tin người dùng",
            description="Cho phép xem danh sách và chi tiết người dùng",
            created_at=self.now,
            updated_at=self.now,
        )

    # 1. tạo/read permission representation
    def test_01_permission_representation_valid(self):
        self.assertEqual(self.permission.id, self.permission_id)
        self.assertEqual(self.permission.code, "user.view")
        self.assertEqual(self.permission.name, "Xem thông tin người dùng")
        self.assertEqual(self.permission.description, "Cho phép xem danh sách và chi tiết người dùng")
        self.assertIsInstance(self.permission.created_at, datetime)
        self.assertIsInstance(self.permission.updated_at, datetime)

    # 2. lookup permission theo code
    @patch("app.repositories.permission_repository._database_cursor")
    def test_02_lookup_permission_by_code(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "id": self.permission_id,
            "code": "user.view",
            "name": "Xem thông tin người dùng",
            "description": "Cho phép xem danh sách và chi tiết người dùng",
            "created_at": self.now,
            "updated_at": self.now,
        }
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        result = permission_repository.get_permission_by_code("user.view")

        self.assertIsNotNone(result)
        self.assertEqual(result.id, self.permission_id)
        self.assertEqual(result.code, "user.view")
        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("WHERE code = %s", sql)
        self.assertEqual(values, ("user.view",))

    # 3. duplicate permission bị xử lý (IntegrityError ném ra)
    @patch("app.repositories.permission_repository._database_cursor")
    def test_03_duplicate_permission_handled(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = IntegrityError("1062 (23000): Duplicate entry 'user.view' for key 'code'")
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        with self.assertRaises(IntegrityError):
            permission_repository.insert_permission(self.permission)

    # 4. permission không tồn tại -> trả về None
    @patch("app.repositories.permission_repository._database_cursor")
    def test_04_permission_not_found(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        result_id = permission_repository.get_permission_by_id("missing-id")
        result_code = permission_repository.get_permission_by_code("missing.code")

        self.assertIsNone(result_id)
        self.assertIsNone(result_code)

    # 5. database error không fallback mock
    @patch("app.repositories.permission_repository._database_cursor")
    def test_05_database_error_no_mock_fallback(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = MySQLError("Database unavailable")
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        with self.assertRaises(MySQLError):
            permission_repository.get_permission_by_id(self.permission_id)

        with self.assertRaises(MySQLError):
            permission_repository.get_all_permissions()

    # 6. parameterized SQL
    @patch("app.repositories.permission_repository._database_cursor")
    def test_06_parameterized_sql_queries(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        malicious_code = "' OR '1'='1"
        permission_repository.get_permission_by_code(malicious_code)

        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("%s", sql)
        self.assertNotIn(malicious_code, sql)
        self.assertEqual(values, (malicious_code,))


if __name__ == "__main__":
    unittest.main()
