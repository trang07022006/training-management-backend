import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask, jsonify
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError

from app.models.login_session import LoginSession
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.services import authorization_service
from app.utils.rbac_auth import permission_required


class Scrum71DefaultDenyTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-71: Áp dụng nguyên tắc Default Deny (Mặc định từ chối truy cập).
    Nguyên tắc cốt lõi:
    - Nếu không xác định được quyền hạn rõ ràng hợp lệ từ Database -> Luôn luôn DENY.
    - Tuyệt đối không chuyển lỗi cơ sở dữ liệu thành ALLOW.
    - Không cho phép truy cập với route chưa cấu hình permission hoặc permission rỗng.
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum71-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
        )
        self.jwt = JWTManager(self.app)

        # Route được bảo vệ với permission chuẩn
        @self.app.route("/api/users", methods=["GET"])
        @permission_required("user.view")
        def list_users():
            return jsonify({"status": "success", "data": ["user1", "user2"]}), 200

        # Route cấu hình permission không hợp lệ / rỗng để test Default Deny
        @self.app.route("/api/unconfigured", methods=["GET"])
        @permission_required("")
        def unconfigured_route():
            return jsonify({"status": "success"}), 200

        self.client = self.app.test_client()

        self.now = datetime.now(timezone.utc)
        self.valid_user_id = "user-alice-123"
        self.valid_session_id = "session-alice-abc"

        self.valid_session = LoginSession(
            session_id=self.valid_session_id,
            user_id=self.valid_user_id,
            refresh_jti="test-refresh-jti-123",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
            revoked_at=None,
        )

    def _create_token(self, user_id=None, session_id=None):
        with self.app.app_context():
            return create_access_token(
                identity=user_id or self.valid_user_id,
                additional_claims={"sid": session_id or self.valid_session_id},
            )

    # 1. no role -> deny (User không được gán bất kỳ vai trò nào trong DB)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.user_repository.get_user_by_id")
    def test_01_no_role_denies(
        self, mock_get_user, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.valid_session
        mock_perm_repo.return_value = Permission(id="p1", code="user.view", name="Xem user")
        mock_ur_roles.return_value = []
        mock_get_user.return_value = User(id=self.valid_user_id, role="")  # Không có role

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")
        self.assertFalse(authorization_service.has_permission(self.valid_user_id, "user.view"))

    # 2. no permission -> deny (Role tồn tại nhưng không có bất kỳ quyền nào)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_02_role_without_permission_denies(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.valid_session
        mock_perm_repo.return_value = Permission(id="p1", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-empty", code="guest", name="Guest")]
        mock_rp_codes.return_value = []  # Role không có quyền nào

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")
        self.assertFalse(authorization_service.has_permission(self.valid_user_id, "user.view"))

    # 3. missing mapping -> deny (Role có quyền khác nhưng thiếu mapping với permission yêu cầu)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_03_missing_mapping_denies(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.valid_session
        mock_perm_repo.return_value = Permission(id="p1", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-trainee", code="trainee", name="Trainee")]
        # Mapping chỉ có course.view, thiếu user.view
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")
        self.assertFalse(authorization_service.has_permission(self.valid_user_id, "user.view"))

    # 4. unknown permission / unconfigured permission -> deny (Default Deny)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    def test_04_unknown_or_unconfigured_permission_denies(
        self, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.valid_session
        mock_perm_repo.return_value = None  # Permission không tồn tại trong hệ thống

        token = self._create_token()

        # Permission rỗng trên route /api/unconfigured -> Phải DENY ngay lập tức
        res_unconfigured = self.client.get(
            "/api/unconfigured", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(res_unconfigured.status_code, 403)
        self.assertEqual(res_unconfigured.get_json()["code"], "FORBIDDEN")

        # Permission code không có trong DB
        self.assertFalse(authorization_service.has_permission(self.valid_user_id, "nonexistent.perm"))

    # 5. unauthenticated -> deny (401)
    def test_05_unauthenticated_denies_with_401(self):
        res = self.client.get("/api/users")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    # 6. DB lookup lỗi -> không allow (Không bao giờ chuyển lỗi DB thành True / Allow)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    def test_06_database_lookup_error_does_not_allow(
        self, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.valid_session
        mock_perm_repo.side_effect = MySQLError("Database connection dropped")

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

        # Phải trả về mã lỗi 500 an toàn, tuyệt đối không trả về 200
        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.get_json()["code"], "DATABASE_ERROR")

    # 7. user có permission rõ ràng từ DB -> allow
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_07_user_with_explicit_permission_allows(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.valid_session
        mock_perm_repo.return_value = Permission(id="p1", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view", "user.manage"]

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")
        self.assertTrue(authorization_service.has_permission(self.valid_user_id, "user.view"))

    # 8. regression SCRUM-70: Kiểm tra tính toàn vẹn của get_user_permissions và has_permission
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_08_scrum70_regression(self, mock_rp_codes, mock_ur_roles, mock_perm_repo):
        mock_perm_repo.side_effect = lambda code: Permission(id=f"p-{code}", code=code, name=code)
        mock_ur_roles.return_value = [Role(id="r-trainer", code="trainer", name="Trainer")]
        mock_rp_codes.return_value = ["user.view", "course.view"]

        self.assertTrue(authorization_service.has_permission(self.valid_user_id, "user.view"))
        self.assertTrue(authorization_service.has_permission(self.valid_user_id, "course.view"))
        self.assertFalse(authorization_service.has_permission(self.valid_user_id, "course.manage"))


if __name__ == "__main__":
    unittest.main()
