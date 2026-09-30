import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from mysql.connector import Error as MySQLError, IntegrityError

from app.models.permission import Permission
from app.models.role import Role
from app.repositories import role_permission_repository


class Scrum62RolePermissionMappingTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-62: Xây dựng quan hệ vai trò và quyền (Role - Permission mapping).
    1. role có nhiều permission
    2. permission có thể thuộc nhiều role
    3. duplicate mapping bị ngăn
    4. invalid role (foreign key violation)
    5. invalid permission (foreign key violation)
    6. lấy đúng permission list
    7. database error không fallback mock
    8. hồi quy SCRUM-60 và SCRUM-61
    """

    def setUp(self):
        self.role_id = "role-trainer-uuid"
        self.perm_1_id = "perm-course-view"
        self.perm_2_id = "perm-course-edit"

    # 1. role có nhiều permission
    @patch("app.repositories.role_permission_repository._database_cursor")
    def test_01_role_can_have_multiple_permissions(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        role_permission_repository.assign_permission_to_role(self.role_id, self.perm_1_id)
        role_permission_repository.assign_permission_to_role(self.role_id, self.perm_2_id)

        self.assertEqual(mock_cursor.execute.call_count, 2)
        call_args_1 = mock_cursor.execute.call_args_list[0][0]
        call_args_2 = mock_cursor.execute.call_args_list[1][0]
        self.assertEqual(call_args_1[1][0], self.role_id)
        self.assertEqual(call_args_1[1][1], self.perm_1_id)
        self.assertEqual(call_args_2[1][0], self.role_id)
        self.assertEqual(call_args_2[1][1], self.perm_2_id)

    # 2. permission có thể thuộc nhiều role
    @patch("app.repositories.role_permission_repository._database_cursor")
    def test_02_permission_can_belong_to_multiple_roles(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        now = datetime.now(timezone.utc)
        mock_cursor.fetchall.return_value = [
            {"id": "role-admin", "code": "admin", "name": "Admin", "description": None, "created_at": now, "updated_at": now},
            {"id": "role-trainer", "code": "trainer", "name": "Trainer", "description": None, "created_at": now, "updated_at": now},
        ]
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        roles = role_permission_repository.get_roles_by_permission_id("perm-course-view")

        self.assertEqual(len(roles), 2)
        self.assertEqual(roles[0].code, "admin")
        self.assertEqual(roles[1].code, "trainer")
        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("WHERE rp.permission_id = %s", sql)
        self.assertEqual(values, ("perm-course-view",))

    # 3. duplicate mapping bị ngăn
    @patch("app.repositories.role_permission_repository._database_cursor")
    def test_03_duplicate_mapping_rejected(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = IntegrityError(
            "1062 (23000): Duplicate entry 'role-trainer-uuid-perm-course-view' for key 'PRIMARY'"
        )
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        with self.assertRaises(IntegrityError):
            role_permission_repository.assign_permission_to_role(self.role_id, self.perm_1_id)

    # 4. invalid role bị từ chối
    @patch("app.repositories.role_permission_repository._database_cursor")
    def test_04_invalid_role_foreign_key_violation(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = IntegrityError("1452 (23000): Cannot add or update a child row: a foreign key constraint fails (`role_permissions`, CONSTRAINT `fk_role_permissions_role`)")
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        with self.assertRaises(IntegrityError):
            role_permission_repository.assign_permission_to_role("invalid-role-id", self.perm_1_id)

    # 5. invalid permission bị từ chối
    @patch("app.repositories.role_permission_repository._database_cursor")
    def test_05_invalid_permission_foreign_key_violation(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = IntegrityError("1452 (23000): Cannot add or update a child row: a foreign key constraint fails (`role_permissions`, CONSTRAINT `fk_role_permissions_permission`)")
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        with self.assertRaises(IntegrityError):
            role_permission_repository.assign_permission_to_role(self.role_id, "invalid-perm-id")

    # 6. lấy đúng danh sách permission và mã permission của role
    @patch("app.repositories.role_permission_repository._database_cursor")
    def test_06_get_permissions_and_codes_by_role_id(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        now = datetime.now(timezone.utc)
        mock_cursor.fetchall.side_effect = [
            [
                {"id": "p1", "code": "course.view", "name": "Xem khóa học", "description": None, "created_at": now, "updated_at": now},
                {"id": "p2", "code": "course.edit", "name": "Sửa khóa học", "description": None, "created_at": now, "updated_at": now},
            ],
            [
                {"code": "course.view"},
                {"code": "course.edit"},
            ],
        ]
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        perms = role_permission_repository.get_permissions_by_role_id(self.role_id)
        codes = role_permission_repository.get_permission_codes_by_role_id(self.role_id)

        self.assertEqual(len(perms), 2)
        self.assertEqual(perms[0].code, "course.view")
        self.assertEqual(perms[1].code, "course.edit")
        self.assertEqual(codes, ["course.view", "course.edit"])

    # 7. database error không fallback mock
    @patch("app.repositories.role_permission_repository._database_cursor")
    def test_07_database_error_no_mock_fallback(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = MySQLError("MySQL query failure")
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        with self.assertRaises(MySQLError):
            role_permission_repository.get_permissions_by_role_id(self.role_id)

        with self.assertRaises(MySQLError):
            role_permission_repository.assign_permission_to_role(self.role_id, self.perm_1_id)

    # 8. thu hồi quyền khỏi vai trò thành công
    @patch("app.repositories.role_permission_repository._database_cursor")
    def test_08_remove_permission_from_role(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        removed = role_permission_repository.remove_permission_from_role(self.role_id, self.perm_1_id)

        self.assertTrue(removed)
        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("DELETE FROM role_permissions", sql)
        self.assertEqual(values, (self.role_id, self.perm_1_id))


if __name__ == "__main__":
    unittest.main()
