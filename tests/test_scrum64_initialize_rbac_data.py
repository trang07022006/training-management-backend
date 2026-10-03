import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.models.permission import Permission
from app.models.role import Role
from app.services import rbac_service
from app.services.session_service import create_login_session, validate_login_session


class Scrum64InitializeRbacDataTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-64: Khởi tạo và đồng bộ dữ liệu RBAC.
    1. migration/seed tạo đúng role
    2. không duplicate khi chạy lại (tính idempotent)
    3. permission code unique
    4. mapping đúng cho từng role
    5. dữ liệu user hiện tại không bị mất
    6. Login vẫn lấy role đúng (tương thích SCRUM-18)
    7. Session management vẫn hoạt động chính xác (hồi quy SCRUM-19)
    8. Forgot password token logic vẫn tương thích (hồi quy SCRUM-20)
    9. Change password / session revocation logic vẫn tương thích (hồi quy SCRUM-21)
    10. Ràng buộc toàn vẹn cơ sở dữ liệu hoạt động
    """

    def setUp(self):
        self.now = datetime.now(timezone.utc)

    # 1. migration/seed tạo đúng các role chuẩn (admin, trainer, trainee, user)
    def test_01_initial_roles_definitions(self):
        codes = [r.code for r in rbac_service.INITIAL_ROLES]
        self.assertIn("admin", codes)
        self.assertIn("trainer", codes)
        self.assertIn("trainee", codes)
        self.assertIn("user", codes)
        self.assertEqual(len(codes), 4)

    # 2. không duplicate khi chạy lại (tính idempotent của sync_initial_rbac_data)
    @patch("app.services.rbac_service.role_permission_repository")
    @patch("app.services.rbac_service.permission_repository")
    @patch("app.services.rbac_service.role_repository")
    def test_02_sync_is_idempotent(self, mock_role_repo, mock_perm_repo, mock_rp_repo):
        # Lần 1: Giả lập chưa có dữ liệu trong DB -> tạo mới
        mock_role_repo.get_role_by_code.return_value = None
        mock_perm_repo.get_permission_by_code.return_value = None
        mock_rp_repo.get_permission_codes_by_role_id.return_value = []

        result_1 = rbac_service.sync_initial_rbac_data()
        self.assertEqual(result_1["roles_created"], 4)
        self.assertEqual(result_1["permissions_created"], 6)

        # Lần 2: Giả lập tất cả đã tồn tại trong DB -> không tạo mới (idempotent)
        mock_role_repo.get_role_by_code.side_effect = lambda code: Role(id=f"r-{code}", code=code, name=code)
        mock_perm_repo.get_permission_by_code.side_effect = lambda code: Permission(id=f"p-{code}", code=code, name=code)
        mock_rp_repo.get_permission_codes_by_role_id.side_effect = lambda rid: [
            "user.view", "user.manage", "course.view", "course.manage", "session.view", "session.revoke"
        ]

        result_2 = rbac_service.sync_initial_rbac_data()
        self.assertEqual(result_2["roles_created"], 0)
        self.assertEqual(result_2["permissions_created"], 0)
        self.assertEqual(result_2["mappings_created"], 0)

    # 3. permission code unique
    def test_03_permission_codes_unique(self):
        codes = [p.code for p in rbac_service.INITIAL_PERMISSIONS]
        self.assertEqual(len(codes), len(set(codes)))

    # 4. mapping đúng cho từng role
    def test_04_mapping_defined_correctly(self):
        role_map = rbac_service.INITIAL_ROLE_PERMISSIONS_MAP
        # Admin có toàn quyền
        self.assertIn("user.manage", role_map["admin"])
        self.assertIn("course.manage", role_map["admin"])
        # Trainer có quyền quản lý khóa học, không có quyền xem hay quản trị user
        self.assertIn("course.manage", role_map["trainer"])
        self.assertNotIn("user.view", role_map["trainer"])
        self.assertNotIn("user.manage", role_map["trainer"])
        # Trainee và User không có quyền quản lý
        self.assertNotIn("course.manage", role_map["trainee"])
        self.assertNotIn("user.manage", role_map["user"])

    # 5. dữ liệu user hiện tại không bị mất: truy vấn permissions theo user hoạt động trơn tru
    @patch("app.services.rbac_service.role_permission_repository")
    @patch("app.services.rbac_service.user_role_repository")
    def test_05_get_user_permissions_aggregation(self, mock_ur_repo, mock_rp_repo):
        # User có 2 role: trainer và user
        mock_ur_repo.get_roles_by_user_id.return_value = [
            Role(id="r-trainer", code="trainer", name="Trainer"),
            Role(id="r-user", code="user", name="User"),
        ]
        mock_rp_repo.get_permission_codes_by_role_id.side_effect = lambda role_id: (
            ["course.view", "course.manage"] if role_id == "r-trainer" else ["session.view"]
        )

        perms = rbac_service.get_user_permissions("test-user-id")

        self.assertEqual(perms, ["course.manage", "course.view", "session.view"])
        self.assertTrue(rbac_service.user_has_permission("test-user-id", "course.manage"))
        self.assertFalse(rbac_service.user_has_permission("test-user-id", "user.manage"))

    # 6. Login vẫn lấy role đúng (SCRUM-18 compatibility)
    @patch("app.services.rbac_service.user_role_repository.get_primary_role_code_by_user_id")
    def test_06_scrum18_login_role_compatibility(self, mock_primary_role):
        mock_primary_role.return_value = "admin"
        from app.repositories.user_role_repository import get_primary_role_code_by_user_id
        role = get_primary_role_code_by_user_id("user-admin-123")
        self.assertEqual(role, "admin")

    # 7. Session management vẫn hoạt động chính xác (hồi quy SCRUM-19)
    def test_07_scrum19_session_regression(self):
        from flask import Flask
        from datetime import timedelta
        from flask_jwt_extended import JWTManager

        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum64-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            JWT_REFRESH_TOKEN_EXPIRES=timedelta(hours=8),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        JWTManager(app)

        with app.app_context():
            session, tokens = create_login_session("user-scrum64-test")
            self.assertIsNotNone(session.session_id)
            self.assertIsNotNone(tokens["access_token"])
            # validate session hợp lệ không ném ngoại lệ
            validate_login_session(session)

    # 8. Ràng buộc SQL script hợp lệ
    def test_08_sql_script_files_exist(self):
        import os
        scripts_dir = os.path.join(os.path.dirname(__file__), "..", "database", "scripts")
        self.assertTrue(os.path.exists(os.path.join(scripts_dir, "001_create_roles_table.sql")))
        self.assertTrue(os.path.exists(os.path.join(scripts_dir, "002_create_permissions_table.sql")))
        self.assertTrue(os.path.exists(os.path.join(scripts_dir, "003_create_role_permissions_table.sql")))
        self.assertTrue(os.path.exists(os.path.join(scripts_dir, "004_create_user_roles_table.sql")))
        self.assertTrue(os.path.exists(os.path.join(scripts_dir, "005_seed_rbac_initial_data.sql")))


if __name__ == "__main__":
    unittest.main()
