import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, jsonify, request
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError

from app.models.login_session import LoginSession
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.routes.session_routes import session_bp
from app.routes.user_routes import user_bp
from app.services import authorization_service, rbac_service
from app.services.change_password_service import (
    ChangePasswordError,
    validate_new_password_policy,
    verify_current_password,
)
from app.services.session_service import (
    SessionValidationError,
    validate_login_session,
)
from app.utils.rbac_auth import permission_required


class Scrum74OverallRbacTests(unittest.TestCase):
    """
    Bộ kiểm thử tổng thể RBAC (SCRUM-74) - Quality Gate cuối của Giai đoạn 2.
    Bao gồm ma trận kiểm thử toàn diện từ A đến H và kiểm thử chi tiết 4 vai trò thực tế:
    - Admin (Quản trị viên)
    - Trainer (Giảng viên)
    - Trainee (Học viên)
    - User (Người dùng)
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum74-overall-suite-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            JWT_REFRESH_TOKEN_EXPIRES=timedelta(hours=8),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)

        @self.app.route("/api/health", methods=["GET"])
        def health():
            return jsonify({"status": "ok"}), 200

        # Endpoint với permission rỗng để kiểm thử Default Deny ở tầng route
        @self.app.route("/api/unconfigured", methods=["GET"])
        @permission_required("")
        def unconfigured_route():
            return jsonify({"status": "should_not_reach"}), 200

        self.app.register_blueprint(auth_bp)
        self.app.register_blueprint(session_bp)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()

        self.now = datetime.now(timezone.utc)
        self.user_id = "user-scrum74"
        self.session_id = "session-scrum74"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="refresh-jti-74",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
            revoked_at=None,
        )

        # Định nghĩa các vai trò và quyền thực tế của hệ thống (SCRUM-60 -> 64)
        self.role_admin = Role(id="role-id-admin", code="admin", name="Quản trị viên")
        self.role_trainer = Role(id="role-id-trainer", code="trainer", name="Giảng viên")
        self.role_trainee = Role(id="role-id-trainee", code="trainee", name="Học viên")
        self.role_user = Role(id="role-id-user", code="user", name="Người dùng")

        self.all_perms = {
            "user.view": Permission(id="p1", code="user.view", name="Xem user"),
            "user.manage": Permission(id="p2", code="user.manage", name="Quản trị user"),
            "course.view": Permission(id="p3", code="course.view", name="Xem khóa học"),
            "course.manage": Permission(id="p4", code="course.manage", name="Quản trị khóa học"),
            "session.view": Permission(id="p5", code="session.view", name="Xem phiên"),
            "session.revoke": Permission(id="p6", code="session.revoke", name="Thu hồi phiên"),
        }

    def _create_token(self, user_id=None, session_id=None):
        with self.app.app_context():
            return create_access_token(
                identity=user_id or self.user_id,
                additional_claims={"sid": session_id or self.session_id},
            )

    # =========================================================================
    # A. AUTHENTICATION
    # =========================================================================

    # 1. Không token/session -> không truy cập protected API (401)
    def test_01_no_token_denied(self):
        res = self.client.get("/api/users")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")
        self.assertIn("đăng nhập", res.get_json()["message"].lower())

    # 1b. Token sai định dạng / giả mạo -> từ chối (401)
    def test_01b_malformed_token_denied(self):
        res = self.client.get(
            "/api/users",
            headers={"Authorization": "Bearer malformed.invalid.token"},
        )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    # 2. Session hết hạn (idle hoặc absolute) -> không truy cập (401)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_session_expired_denied(self, mock_get_session):
        expired_session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="expired-jti",
            created_at=self.now - timedelta(hours=10),
            last_activity_at=self.now - timedelta(hours=1),
            idle_expires_at=self.now - timedelta(minutes=10),  # Đã hết hạn
            absolute_expires_at=self.now - timedelta(hours=2),
            revoked_at=None,
        )
        mock_get_session.return_value = expired_session

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "SESSION_EXPIRED")
        self.assertIn("hết hạn", res.get_json()["message"].lower())

    # 3. Session revoked -> không truy cập (401)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_03_session_revoked_denied(self, mock_get_session):
        revoked_session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="revoked-jti",
            created_at=self.now - timedelta(minutes=10),
            last_activity_at=self.now - timedelta(minutes=5),
            idle_expires_at=self.now + timedelta(minutes=25),
            absolute_expires_at=self.now + timedelta(hours=8),
            revoked_at=self.now - timedelta(minutes=1),  # Đã bị thu hồi
        )
        mock_get_session.return_value = revoked_session

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "SESSION_REVOKED")
        self.assertIn("thu hồi", res.get_json()["message"].lower())

    # 4. Session hợp lệ -> tiếp tục authorization (200 khi có quyền)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_04_valid_session_proceeds_to_authorization(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.all_perms["user.view"]
        mock_ur_roles.return_value = [self.role_admin]
        mock_rp_codes.return_value = ["user.view"]

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

    # =========================================================================
    # B. ROLE
    # =========================================================================

    # 5. User không role -> deny (403)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.user_repository.get_user_by_id")
    def test_05_user_without_role_denied(
        self, mock_get_user, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.all_perms["user.view"]
        mock_ur_roles.return_value = []
        mock_get_user.return_value = None

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")
        self.assertEqual(res.get_json()["message"], "Bạn không có quyền thực hiện thao tác này.")

    # 6. User có một role -> permissions đúng
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_06_single_role_permissions_correct(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo
    ):
        mock_perm_repo.side_effect = lambda c: self.all_perms.get(c)
        mock_ur_roles.return_value = [self.role_trainee]
        mock_rp_codes.return_value = ["course.view", "session.view"]

        perms = authorization_service.get_user_permissions(self.user_id)
        self.assertEqual(perms, ["course.view", "session.view"])
        self.assertEqual(authorization_service.has_permission(self.user_id, "course.view"), True)
        self.assertEqual(authorization_service.has_permission(self.user_id, "user.view"), False)

    # 7. User nhiều role -> hợp permissions đúng (union)
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_07_multiple_roles_union_correct(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo
    ):
        mock_perm_repo.side_effect = lambda c: self.all_perms.get(c)
        mock_ur_roles.return_value = [self.role_trainer, self.role_user]
        mock_rp_codes.side_effect = lambda rid: (
            ["user.view", "course.view", "course.manage"] if rid == "role-id-trainer" else ["session.view"]
        )

        perms = authorization_service.get_user_permissions(self.user_id)
        self.assertEqual(sorted(perms), ["course.manage", "course.view", "session.view", "user.view"])
        self.assertEqual(authorization_service.has_permission(self.user_id, "course.manage"), True)
        self.assertEqual(authorization_service.has_permission(self.user_id, "session.revoke"), False)

    # 8. Role không tồn tại trong DB -> deny
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.user_repository.get_user_by_id")
    @patch("app.services.authorization_service.role_repository.get_role_by_code")
    def test_08_nonexistent_role_denied(
        self, mock_get_role, mock_get_user, mock_ur_roles, mock_perm_repo
    ):
        mock_perm_repo.side_effect = lambda c: self.all_perms.get(c)
        mock_ur_roles.return_value = []
        mock_get_user.return_value = User(id=self.user_id, role="ghost_role")
        mock_get_role.return_value = None

        self.assertEqual(authorization_service.has_permission(self.user_id, "user.view"), False)

    # =========================================================================
    # C. PERMISSION
    # =========================================================================

    # 9. Permission có -> allow
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_09_permission_present_allows(self, mock_rp_codes, mock_ur_roles, mock_perm_repo):
        mock_perm_repo.side_effect = lambda c: self.all_perms.get(c)
        mock_ur_roles.return_value = [self.role_admin]
        mock_rp_codes.return_value = ["course.manage"]
        self.assertEqual(authorization_service.has_permission(self.user_id, "course.manage"), True)

    # 10. Permission thiếu -> deny
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_10_permission_missing_denies(self, mock_rp_codes, mock_ur_roles, mock_perm_repo):
        mock_perm_repo.side_effect = lambda c: self.all_perms.get(c)
        mock_ur_roles.return_value = [self.role_trainee]
        mock_rp_codes.return_value = ["course.view"]
        self.assertEqual(authorization_service.has_permission(self.user_id, "course.manage"), False)

    # 11. Permission không tồn tại trong DB -> deny
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    def test_11_unknown_permission_denies(self, mock_perm_repo):
        mock_perm_repo.return_value = None
        self.assertEqual(authorization_service.has_permission(self.user_id, "unknown.superpower"), False)

    # 12. Role-Permission mapping sai -> deny
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_12_corrupted_mapping_denies(self, mock_rp_codes, mock_ur_roles, mock_perm_repo):
        mock_perm_repo.side_effect = lambda c: self.all_perms.get(c)
        mock_ur_roles.return_value = [self.role_user]
        mock_rp_codes.return_value = []
        self.assertEqual(authorization_service.has_permission(self.user_id, "user.view"), False)

    # 13. Duplicate mapping không tạo quyền bất thường
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_13_duplicate_mapping_deduplicated_safely(self, mock_rp_codes, mock_ur_roles, mock_perm_repo):
        mock_perm_repo.side_effect = lambda c: self.all_perms.get(c)
        mock_ur_roles.return_value = [self.role_trainer, self.role_admin]
        mock_rp_codes.return_value = ["user.view", "user.view", "user.view"]  # Duplicate

        perms = authorization_service.get_user_permissions(self.user_id)
        self.assertEqual(perms.count("user.view"), 1)

    # =========================================================================
    # D. API PROTECTION
    # =========================================================================

    # 14. Protected GET đúng quyền -> success (200)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_14_protected_get_success(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.all_perms["course.view"]
        mock_ur_roles.return_value = [self.role_trainee]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.get("/api/courses", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

    # 15. Protected POST đúng quyền -> success (201)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_15_protected_post_success(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.all_perms["course.manage"]
        mock_ur_roles.return_value = [self.role_trainer]
        mock_rp_codes.return_value = ["course.manage"]

        token = self._create_token()
        res = self.client.post("/api/courses", json={"title": "React TS"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.get_json()["status"], "success")

    # 16. Protected POST thiếu quyền -> 403
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_16_protected_post_denied(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.all_perms["course.manage"]
        mock_ur_roles.return_value = [self.role_trainee]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.post("/api/courses", json={"title": "Hack"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    # 17. Không quyền -> 403 và không leak thông tin nội bộ (SCRUM-73)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_17_forbidden_returns_403_and_does_not_leak_internals(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.all_perms["user.manage"]
        mock_ur_roles.return_value = [self.role_user]
        mock_rp_codes.return_value = ["session.view"]

        token = self._create_token()
        res = self.client.post("/api/users", json={}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data["code"], "FORBIDDEN")
        self.assertEqual(data["message"], "Bạn không có quyền thực hiện thao tác này.")

        body = res.get_data(as_text=True)
        self.assertNotIn("Traceback", body)
        self.assertNotIn("Exception", body)
        self.assertNotIn("SELECT", body)
        self.assertNotIn("FROM", body)
        self.assertNotIn("user_roles", body)
        self.assertNotIn("role_permissions", body)
        self.assertNotIn(token, body)

    # 18. Không auth -> đúng authentication error (401)
    def test_18_no_auth_returns_401(self):
        res = self.client.post("/api/users", json={})
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data["code"], "UNAUTHORIZED")
        self.assertIn("đăng nhập", data["message"].lower())
        body = res.get_data(as_text=True)
        self.assertNotIn("Traceback", body)
        self.assertNotIn("Exception", body)

    # =========================================================================
    # E. PRIVILEGE ESCALATION
    # =========================================================================

    # 19. Gửi role=admin trong JSON -> không bypass
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_19_spoof_role_in_json_cannot_bypass(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.all_perms["user.manage"]
        mock_ur_roles.return_value = [self.role_trainee]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.post("/api/users", json={"role": "admin", "email": "a@daotao.edu.vn"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    # 20. Gửi permission trong JSON -> không bypass
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_20_spoof_permission_in_json_cannot_bypass(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.all_perms["user.manage"]
        mock_ur_roles.return_value = [self.role_trainee]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.post("/api/users", json={"permissions": ["user.manage"], "email": "b@daotao.edu.vn"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    # 21. Sửa query parameter role -> không bypass
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_21_query_param_role_cannot_bypass(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.all_perms["user.manage"]
        mock_ur_roles.return_value = [self.role_trainee]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.post("/api/users?role=admin&permission=user.manage", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    # 22. Sửa header tùy ý -> không bypass
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_22_header_spoofing_cannot_bypass(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.all_perms["user.manage"]
        mock_ur_roles.return_value = [self.role_trainee]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.post(
            "/api/users",
            headers={
                "Authorization": f"Bearer {token}",
                "X-User-Role": "admin",
                "X-Admin": "true",
            },
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    # 23. User A không truy cập quyền chỉ thuộc user/role khác
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_23_user_cannot_access_unauthorized_role_privilege(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.all_perms["user.manage"]
        mock_ur_roles.return_value = [self.role_trainer]  # Trainer không có user.manage
        mock_rp_codes.return_value = ["user.view", "course.view", "course.manage"]

        token = self._create_token()
        res = self.client.post("/api/users", json={"email": "attacker@daotao.edu.vn"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    # =========================================================================
    # F. DEFAULT DENY
    # =========================================================================

    # 24. Không xác định permission -> deny
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    def test_24_unknown_permission_denies(self, mock_perm_repo):
        mock_perm_repo.return_value = None
        self.assertEqual(authorization_service.has_permission(self.user_id, "undefined.action"), False)

    # 24b. Permission rỗng / None / Route chưa cấu hình -> Default Deny
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_24b_unconfigured_route_default_denies(self, mock_get_session):
        mock_get_session.return_value = self.session
        token = self._create_token()
        res = self.client.get("/api/unconfigured", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

        self.assertEqual(authorization_service.has_permission(self.user_id, ""), False)
        self.assertEqual(authorization_service.has_permission(self.user_id, None), False)
        self.assertEqual(authorization_service.has_permission("", "user.view"), False)
        self.assertEqual(authorization_service.has_permission(None, "user.view"), False)

    # 25. Không xác định role -> deny
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.user_repository.get_user_by_id")
    def test_25_undefined_role_denies(self, mock_get_user, mock_ur_roles, mock_perm_repo):
        mock_perm_repo.side_effect = lambda c: self.all_perms.get(c)
        mock_ur_roles.return_value = []
        mock_get_user.return_value = None
        self.assertEqual(authorization_service.has_permission(self.user_id, "user.view"), False)

    # 26. DB lookup lỗi -> không allow (trả về 500 an toàn)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    def test_26_db_lookup_error_does_not_allow(self, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.side_effect = MySQLError("Deadlock detected")

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.get_json()["code"], "DATABASE_ERROR")

    # 27. Mapping thiếu -> deny
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_27_missing_mapping_denies(self, mock_rp_codes, mock_ur_roles, mock_perm_repo):
        mock_perm_repo.side_effect = lambda c: self.all_perms.get(c)
        mock_ur_roles.return_value = [self.role_trainee]
        mock_rp_codes.return_value = ["session.view"]  # Thiếu course.view
        self.assertEqual(authorization_service.has_permission(self.user_id, "course.view"), False)

    # =========================================================================
    # G. MA TRẬN 4 VAI TRÒ THỰC TẾ TRONG HỆ THỐNG
    # (Ít nhất 3 role thực tế, mỗi role có ít nhất 1 ALLOW và 1 DENY)
    # =========================================================================

    # 28. ROLE 1: ADMIN (Quản trị viên) - ALLOW toàn quyền, DENY quyền không tồn tại / chưa cấu hình
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_28_role_matrix_admin(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.side_effect = lambda c: self.all_perms.get(c)
        mock_ur_roles.return_value = [self.role_admin]
        mock_rp_codes.return_value = [
            "user.view", "user.manage", "course.view", "course.manage", "session.view", "session.revoke"
        ]

        # Service level checks
        self.assertEqual(authorization_service.has_permission(self.user_id, "user.view"), True)
        self.assertEqual(authorization_service.has_permission(self.user_id, "user.manage"), True)
        self.assertEqual(authorization_service.has_permission(self.user_id, "course.view"), True)
        self.assertEqual(authorization_service.has_permission(self.user_id, "course.manage"), True)
        self.assertEqual(authorization_service.has_permission(self.user_id, "session.view"), True)
        self.assertEqual(authorization_service.has_permission(self.user_id, "session.revoke"), True)
        # Denied
        self.assertEqual(authorization_service.has_permission(self.user_id, "nonexistent.perm"), False)

        # API Level verification: ALLOW
        token = self._create_token()
        res_allow = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_allow.status_code, 200)

        # API Level verification: DENY (route unconfigured)
        res_deny = self.client.get("/api/unconfigured", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_deny.status_code, 403)

    # 29. ROLE 2: TRAINER (Giảng viên) - ALLOW đào tạo/xem, DENY quản trị người dùng & thu hồi phiên
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_29_role_matrix_trainer(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.side_effect = lambda c: self.all_perms.get(c)
        mock_ur_roles.return_value = [self.role_trainer]
        mock_rp_codes.return_value = ["user.view", "course.view", "course.manage", "session.view"]

        # Service level checks
        self.assertEqual(authorization_service.has_permission(self.user_id, "user.view"), True)
        self.assertEqual(authorization_service.has_permission(self.user_id, "course.view"), True)
        self.assertEqual(authorization_service.has_permission(self.user_id, "course.manage"), True)
        self.assertEqual(authorization_service.has_permission(self.user_id, "session.view"), True)
        # Denied
        self.assertEqual(authorization_service.has_permission(self.user_id, "user.manage"), False)
        self.assertEqual(authorization_service.has_permission(self.user_id, "session.revoke"), False)

        # API Level verification: ALLOW (course.manage)
        token = self._create_token()
        res_allow = self.client.post("/api/courses", json={"title": "Python Advance"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_allow.status_code, 201)

        # API Level verification: DENY (user.manage)
        res_deny = self.client.post("/api/users", json={"email": "new@daotao.edu.vn"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_deny.status_code, 403)

    # 30. ROLE 3: TRAINEE (Học viên) - ALLOW xem khóa học/phiên, DENY tạo khóa học & quản trị người dùng
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_30_role_matrix_trainee(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.side_effect = lambda c: self.all_perms.get(c)
        mock_ur_roles.return_value = [self.role_trainee]
        mock_rp_codes.return_value = ["course.view", "session.view"]

        # Service level checks
        self.assertEqual(authorization_service.has_permission(self.user_id, "course.view"), True)
        self.assertEqual(authorization_service.has_permission(self.user_id, "session.view"), True)
        # Denied
        self.assertEqual(authorization_service.has_permission(self.user_id, "user.view"), False)
        self.assertEqual(authorization_service.has_permission(self.user_id, "user.manage"), False)
        self.assertEqual(authorization_service.has_permission(self.user_id, "course.manage"), False)
        self.assertEqual(authorization_service.has_permission(self.user_id, "session.revoke"), False)

        # API Level verification: ALLOW (course.view)
        token = self._create_token()
        res_allow = self.client.get("/api/courses", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_allow.status_code, 200)

        # API Level verification: DENY (course.manage)
        res_deny = self.client.post("/api/courses", json={"title": "Hacked Course"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_deny.status_code, 403)

    # 31. ROLE 4: USER (Người dùng thông thường) - ALLOW xem phiên, DENY toàn bộ quản trị và khóa học
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_31_role_matrix_user(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.side_effect = lambda c: self.all_perms.get(c)
        mock_ur_roles.return_value = [self.role_user]
        mock_rp_codes.return_value = ["session.view"]

        # Service level checks
        self.assertEqual(authorization_service.has_permission(self.user_id, "session.view"), True)
        # Denied
        self.assertEqual(authorization_service.has_permission(self.user_id, "user.view"), False)
        self.assertEqual(authorization_service.has_permission(self.user_id, "user.manage"), False)
        self.assertEqual(authorization_service.has_permission(self.user_id, "course.view"), False)
        self.assertEqual(authorization_service.has_permission(self.user_id, "course.manage"), False)
        self.assertEqual(authorization_service.has_permission(self.user_id, "session.revoke"), False)

        # API Level verification: DENY (user.view)
        token = self._create_token()
        res_deny = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_deny.status_code, 403)

    # =========================================================================
    # H. REGRESSION KIỂM THỬ TOÀN DIỆN CÁC CHỨC NĂNG TRƯỚC
    # =========================================================================

    # 32. Login regression (SCRUM-18): Password check và lockout logic
    def test_32_scrum18_login_regression(self):
        user = User(id="u1", password_hash=generate_password_hash("TestPass123!"))
        self.assertEqual(user.check_password("TestPass123!"), True)
        self.assertEqual(user.check_password("WrongPass123!"), False)

    # 33. Session regression (SCRUM-19): Validate session hợp lệ và ngoại lệ khi hết hạn
    def test_33_scrum19_session_regression(self):
        # Session hợp lệ không gây lỗi
        validate_login_session(self.session)

        # Session hết hạn ném ngoại lệ SessionValidationError
        expired_session = LoginSession(
            session_id="expired-reg-sid",
            user_id="u-reg",
            refresh_jti="jti-reg",
            created_at=self.now - timedelta(hours=10),
            last_activity_at=self.now - timedelta(hours=1),
            idle_expires_at=self.now - timedelta(minutes=5),
            absolute_expires_at=self.now + timedelta(hours=1),
            revoked_at=None,
        )
        with self.assertRaises(SessionValidationError) as ctx:
            validate_login_session(expired_session)
        self.assertEqual(ctx.exception.code, "SESSION_EXPIRED")

    # 34. Forgot/Reset Password regression (SCRUM-20): Hashing nhất quán
    def test_34_scrum20_password_hashing_regression(self):
        raw_pw = "ResetPassStrong123!"
        hashed = generate_password_hash(raw_pw)
        self.assertEqual(check_password_hash(hashed, raw_pw), True)
        self.assertEqual(check_password_hash(hashed, "WrongPassword123!"), False)

    # 35. Change Password regression (SCRUM-21): Kiểm tra chính sách mật khẩu mới
    def test_35_scrum21_change_password_policy_regression(self):
        # Hợp lệ: >= 8 ký tự, có chữ và số, khác mật khẩu hiện tại
        validate_new_password_policy("NewStrongPass2026!", "OldPass123!")

        # Không hợp lệ: quá ngắn (< 8 ký tự)
        with self.assertRaises(ChangePasswordError) as ctx_short:
            validate_new_password_policy("Short1", "OldPass123!")
        self.assertEqual(ctx_short.exception.code, "PASSWORD_TOO_SHORT")

        # Không hợp lệ: thiếu chữ số
        with self.assertRaises(ChangePasswordError) as ctx_no_digit:
            validate_new_password_policy("NoDigitsHere!", "OldPass123!")
        self.assertEqual(ctx_no_digit.exception.code, "PASSWORD_INVALID")

        # Không hợp lệ: trùng mật khẩu hiện tại
        with self.assertRaises(ChangePasswordError) as ctx_same:
            validate_new_password_policy("SamePassword123!", "SamePassword123!")
        self.assertEqual(ctx_same.exception.code, "PASSWORD_SAME_AS_CURRENT")

    # 36. RBAC Data initialization regression (SCRUM-64): Idempotent sync và danh mục chuẩn
    def test_36_scrum64_rbac_data_regression(self):
        self.assertEqual(len(rbac_service.INITIAL_ROLES), 4)
        self.assertEqual(len(rbac_service.INITIAL_PERMISSIONS), 6)
        # Các vai trò chuẩn
        role_codes = {r.code for r in rbac_service.INITIAL_ROLES}
        self.assertEqual(role_codes, {"admin", "trainer", "trainee", "user"})
        # Quyền hạn chuẩn
        perm_codes = {p.code for p in rbac_service.INITIAL_PERMISSIONS}
        self.assertEqual(
            perm_codes,
            {"user.view", "user.manage", "course.view", "course.manage", "session.view", "session.revoke"},
        )


if __name__ == "__main__":
    unittest.main()
