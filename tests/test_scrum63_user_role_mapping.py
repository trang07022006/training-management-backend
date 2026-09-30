import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from mysql.connector import Error as MySQLError, IntegrityError

from app.models.role import Role
from app.repositories import user_role_repository


class Scrum63UserRoleMappingTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-63: Quan hệ Người dùng - Vai trò (User - Role mapping).
    1. user được gán role
    2. user lấy được role
    3. multiple role nếu requirement cho phép
    4. duplicate user-role mapping bị ngăn
    5. invalid user (kiểm tra an toàn)
    6. invalid role (foreign key violation)
    7. Login role lookup vẫn hoạt động (tương thích ngược SCRUM-18)
    8. session/auth logic vẫn tương thích
    9. user khác không bị ảnh hưởng
    10. database error không fallback mock
    """

    def setUp(self):
        self.user_id = "user-alice-123"
        self.role_1_id = "role-admin-uuid"
        self.role_2_id = "role-trainer-uuid"
        self.now = datetime.now(timezone.utc)

    # 1. user được gán role
    @patch("app.repositories.user_role_repository._database_cursor")
    def test_01_assign_role_to_user(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        user_role_repository.assign_role_to_user(self.user_id, self.role_1_id)

        mock_cursor.execute.assert_called_once()
        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("INSERT INTO user_roles", sql)
        self.assertEqual(values[0], self.user_id)
        self.assertEqual(values[1], self.role_1_id)

    # 2. user lấy được role
    @patch("app.repositories.user_role_repository._database_cursor")
    def test_02_get_roles_by_user_id(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "id": self.role_1_id,
                "code": "admin",
                "name": "Quản trị viên",
                "description": None,
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        roles = user_role_repository.get_roles_by_user_id(self.user_id)

        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0].code, "admin")
        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("WHERE ur.user_id = %s", sql)
        self.assertEqual(values, (self.user_id,))

    # 3. multiple role: người dùng có thể sở hữu nhiều role đồng thời
    @patch("app.repositories.user_role_repository._database_cursor")
    def test_03_user_can_have_multiple_roles(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"id": self.role_1_id, "code": "admin", "name": "Admin", "description": None, "created_at": self.now, "updated_at": self.now},
            {"id": self.role_2_id, "code": "trainer", "name": "Trainer", "description": None, "created_at": self.now, "updated_at": self.now},
        ]
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        role_codes = user_role_repository.get_role_codes_by_user_id(self.user_id)

        self.assertEqual(role_codes, ["admin", "trainer"])

    # 4. duplicate user-role mapping bị ngăn (IntegrityError)
    @patch("app.repositories.user_role_repository._database_cursor")
    def test_04_duplicate_user_role_mapping_rejected(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = IntegrityError(
            "1062 (23000): Duplicate entry 'user-alice-123-role-admin-uuid' for key 'PRIMARY'"
        )
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        with self.assertRaises(IntegrityError):
            user_role_repository.assign_role_to_user(self.user_id, self.role_1_id)

    # 5. invalid user: kiểm tra user rỗng / không hợp lệ
    @patch("app.repositories.user_role_repository._database_cursor")
    def test_05_invalid_user_handling(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        roles = user_role_repository.get_roles_by_user_id("")
        self.assertIsInstance(roles, list)
        self.assertEqual(len(roles), 0)

    # 6. invalid role: khóa ngoại không hợp lệ ném IntegrityError
    @patch("app.repositories.user_role_repository._database_cursor")
    def test_06_invalid_role_foreign_key_violation(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = IntegrityError(
            "1452 (23000): Cannot add or update a child row: a foreign key constraint fails (`user_roles`, CONSTRAINT `fk_user_roles_role`)"
        )
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        with self.assertRaises(IntegrityError):
            user_role_repository.assign_role_to_user(self.user_id, "non-existent-role")

    # 7. Login role lookup tương thích ngược: get_primary_role_code_by_user_id
    @patch("app.repositories.user_role_repository._database_cursor")
    def test_07_login_single_role_lookup_compatibility(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"code": "trainer"},
            {"code": "trainee"},
        ]
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        primary_role = user_role_repository.get_primary_role_code_by_user_id(self.user_id)

        # trainer có độ ưu tiên cao hơn trainee
        self.assertEqual(primary_role, "trainer")

    # 8. người dùng không có role trả về None an toàn cho luồng Login
    @patch("app.repositories.user_role_repository._database_cursor")
    def test_08_user_without_roles_returns_none(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        primary_role = user_role_repository.get_primary_role_code_by_user_id("user-no-role")
        self.assertIsNone(primary_role)

    # 9. user khác không bị ảnh hưởng khi truy vấn hoặc xóa
    @patch("app.repositories.user_role_repository._database_cursor")
    def test_09_other_users_roles_not_affected(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        removed = user_role_repository.remove_role_from_user(self.user_id, self.role_1_id)

        self.assertTrue(removed)
        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("DELETE FROM user_roles", sql)
        self.assertIn("user_id = %s", sql)
        self.assertEqual(values, (self.user_id, self.role_1_id))

    # 10. database error không fallback mock
    @patch("app.repositories.user_role_repository._database_cursor")
    def test_10_database_error_no_mock_fallback(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = MySQLError("Database deadlock on user_roles")
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        with self.assertRaises(MySQLError):
            user_role_repository.get_roles_by_user_id(self.user_id)

        with self.assertRaises(MySQLError):
            user_role_repository.assign_role_to_user(self.user_id, self.role_1_id)


if __name__ == "__main__":
    unittest.main()
