import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask, jsonify, request
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError

from app.models.login_session import LoginSession
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.services import authorization_service
from app.utils.rbac_auth import permission_required, require_permission


class Scrum70PermissionAuthorizationTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-70: Xây dựng cơ chế kiểm tra quyền (Authorization Layer).
    Yêu cầu tối thiểu:
    1. user có permission -> ALLOW
    2. user không có permission -> DENY
    3. unauthenticated -> DENY (401)
    4. user không tồn tại -> DENY
    5. role không tồn tại -> DENY
    6. permission không tồn tại -> DENY
    7. multiple roles -> union quyền đúng từ tất cả các role
    8. không tin permission / role mà client gửi lên
    9. database error được xử lý an toàn
    10. không fallback mock khi xảy ra lỗi
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum70-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
        )
        self.jwt = JWTManager(self.app)

        # Định nghĩa một route mẫu bảo vệ bằng decorator @permission_required
        @self.app.route("/api/test-protected", methods=["GET", "POST"])
        @permission_required("user.view")
        def protected_view():
            return jsonify({"status": "success", "data": "authorized_content"}), 200

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

    # 1. user có permission -> ALLOW (trả về 200 và dữ liệu mong muốn)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_01_user_has_permission_allows_access(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.valid_session
        mock_perm_repo.return_value = Permission(id="p1", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r1", code="trainer", name="Trainer")]
        mock_rp_codes.return_value = ["user.view", "course.view"]

        token = self._create_token()
        res = self.client.get(
            "/api/test-protected",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

    # 2. user không có permission -> DENY (trả về 403 Forbidden)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_02_user_lacks_permission_denies_with_403(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.valid_session
        mock_perm_repo.return_value = Permission(id="p1", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r2", code="trainee", name="Trainee")]
        # Trainee chỉ có course.view, không có user.view
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.get(
            "/api/test-protected",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data["code"], "FORBIDDEN")
        self.assertIn("Bạn không có quyền thực hiện thao tác này.", data["message"])

    # 3. unauthenticated -> DENY (trả về 401 Unauthorized khi không có token)
    def test_03_unauthenticated_request_denies_with_401(self):
        res = self.client.get("/api/test-protected")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    # 4. user không tồn tại / không có thông tin trong DB -> DENY
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.user_repository.get_user_by_id")
    def test_04_user_not_found_in_database_denies(
        self, mock_get_user, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.valid_session
        mock_perm_repo.return_value = Permission(id="p1", code="user.view", name="Xem user")
        mock_ur_roles.return_value = []
        mock_get_user.return_value = None  # User không tồn tại

        token = self._create_token()
        res = self.client.get(
            "/api/test-protected",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(res.status_code, 403)
        self.assertFalse(authorization_service.has_permission("non-existent-user", "user.view"))

    # 5. role không tồn tại hoặc bị xóa -> DENY
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.user_repository.get_user_by_id")
    @patch("app.services.authorization_service.role_repository.get_role_by_code")
    def test_05_role_not_existing_denies(
        self, mock_get_role, mock_get_user, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.valid_session
        mock_perm_repo.return_value = Permission(id="p1", code="user.view", name="Xem user")
        mock_ur_roles.return_value = []
        mock_get_user.return_value = User(id=self.valid_user_id, role="deleted_role")
        mock_get_role.return_value = None  # Role không có trong DB

        token = self._create_token()
        res = self.client.get(
            "/api/test-protected",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(res.status_code, 403)
        self.assertFalse(authorization_service.has_permission(self.valid_user_id, "user.view"))

    # 6. permission không tồn tại trong danh mục hệ thống -> DENY
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    def test_06_unknown_permission_denies(self, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.valid_session
        mock_perm_repo.return_value = None  # Permission không tồn tại trong DB

        self.assertFalse(authorization_service.has_permission(self.valid_user_id, "unknown.action"))
        self.assertFalse(authorization_service.has_permission(self.valid_user_id, ""))
        self.assertFalse(authorization_service.has_permission("", "user.view"))

    # 7. multiple roles -> hợp (union) quyền đúng nếu user sở hữu nhiều role
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_07_multiple_roles_union_permissions(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo
    ):
        mock_perm_repo.side_effect = lambda code: Permission(id=f"p-{code}", code=code, name=code)
        # Giả lập user có 2 role: Trainer và User
        mock_ur_roles.return_value = [
            Role(id="r-trainer", code="trainer", name="Trainer"),
            Role(id="r-user", code="user", name="User"),
        ]
        mock_rp_codes.side_effect = lambda r_id: (
            ["course.view", "course.manage"] if r_id == "r-trainer" else ["session.view"]
        )

        user_perms = authorization_service.get_user_permissions(self.valid_user_id)
        self.assertEqual(user_perms, ["course.manage", "course.view", "session.view"])

        # Quyền từ role trainer
        self.assertTrue(authorization_service.has_permission(self.valid_user_id, "course.manage"))
        # Quyền từ role user
        self.assertTrue(authorization_service.has_permission(self.valid_user_id, "session.view"))
        # Quyền không thuộc role nào
        self.assertFalse(authorization_service.has_permission(self.valid_user_id, "user.manage"))

    # 8. không tin permission hoặc role mà client gửi lên trong payload / params / headers
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_08_do_not_trust_client_supplied_role_or_permission(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.valid_session
        mock_perm_repo.return_value = Permission(id="p1", code="user.view", name="Xem user")
        # Trong database, user chỉ là trainee không có quyền user.view
        mock_ur_roles.return_value = [Role(id="r-trainee", code="trainee", name="Trainee")]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()

        # Client cố gắng gửi payload hoặc header tự xưng là admin và tự nhận quyền
        malicious_payload = {
            "role": "admin",
            "permissions": ["user.view", "user.manage"],
            "user_id": "admin-super-user",
        }

        res = self.client.post(
            "/api/test-protected?role=admin&permission=user.view",
            json=malicious_payload,
            headers={
                "Authorization": f"Bearer {token}",
                "X-User-Role": "admin",
                "X-User-Permissions": "user.view,user.manage",
            },
        )

        # Hệ thống phải dựa vào DB, không tin client -> 403 Forbidden
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    # 9. database error được xử lý an toàn
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    def test_09_database_error_handled_safely(self, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.valid_session
        mock_perm_repo.side_effect = MySQLError("Database connection timeout")

        token = self._create_token()
        res = self.client.get(
            "/api/test-protected",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Lỗi DB không được phép thành ALLOW, trả về 500 an toàn
        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.get_json()["code"], "DATABASE_ERROR")

    # 10. không fallback mock khi xảy ra lỗi
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    def test_10_no_mock_fallback_on_db_error(self, mock_perm_repo):
        mock_perm_repo.side_effect = MySQLError("DB unavailable")

        with self.assertRaises(MySQLError):
            authorization_service.has_permission(self.valid_user_id, "user.view")

    # 11. Kiểm tra alias require_permission hoạt động đồng nhất
    def test_11_require_permission_alias(self):
        self.assertIs(require_permission, permission_required)


if __name__ == "__main__":
    unittest.main()
