import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.models.login_session import LoginSession
from app.routes.user_role_routes import user_role_bp
from app.services.user_role_service import UserRoleServiceError


class Scrum102OverallRoleManagementTests(unittest.TestCase):
    """
    SCRUM-102: Kiểm thử tổng thể Quản trị vai trò người dùng (SCRUM-26 Test Matrix)
    
    A. Query
    1. get user roles
    2. list valid roles
    
    B. Assign
    3. valid assignment
    4. duplicate
    5. invalid user
    6. invalid role
    
    C. Revoke
    7. valid revoke
    8. mapping not found
    9. user not found
    10. role not found
    
    D. Security
    11. 401 unauthenticated
    12. 403 forbidden
    13. authorized success
    14. default deny
    15. SQL injection input treated safely as data
    16. no sensitive data leakage (no password hash, salt, DB internals)
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum102-overall-suite-32-chars-min",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_role_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.admin_user_id = "admin-user-102"
        self.session_id = "session-102"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.admin_user_id,
            refresh_jti="ref-jti-102",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.admin_token = create_access_token(
                identity=self.admin_user_id,
                additional_claims={"sid": self.session_id},
            )
            self.unprivileged_token = create_access_token(
                identity="unprivileged-user-102",
                additional_claims={"sid": "unprivileged-session-102"},
            )

    # =========================================================================
    # A. QUERY MATRIX
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.get_user_roles")
    def test_01_query_get_user_roles(self, mock_get_roles, mock_sess, mock_perm):
        """1. Lấy danh sách vai trò hiện tại của người dùng thành công."""
        mock_sess.return_value = self.session
        mock_get_roles.return_value = {
            "user_id": "10",
            "roles": [{"id": "2", "code": "trainer", "name": "Giảng viên"}],
        }

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.get("/api/users/10/roles", headers=headers)

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["user_id"], "10")
        self.assertEqual(len(data["data"]["roles"]), 1)
        self.assertEqual(data["data"]["roles"][0]["code"], "trainer")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.get_available_roles")
    def test_02_query_list_valid_roles(self, mock_avail_roles, mock_sess, mock_perm):
        """2. Lấy danh mục các vai trò khả dụng trong hệ thống."""
        mock_sess.return_value = self.session
        mock_avail_roles.return_value = [
            {"id": "1", "code": "admin", "name": "Quản trị viên"},
            {"id": "2", "code": "trainer", "name": "Giảng viên"},
            {"id": "3", "code": "trainee", "name": "Học viên"},
        ]

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.get("/api/roles", headers=headers)

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]["items"]), 3)
        codes = [r["code"] for r in data["data"]["items"]]
        self.assertIn("admin", codes)
        self.assertIn("trainer", codes)
        self.assertIn("trainee", codes)

    # =========================================================================
    # B. ASSIGN MATRIX
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.assign_role_to_user")
    def test_03_assign_valid_role_success(self, mock_assign, mock_sess, mock_perm):
        """3. Phân vai trò hợp lệ cho người dùng thành công -> 201 Created."""
        mock_sess.return_value = self.session
        mock_assign.return_value = {
            "user_id": "10",
            "role": {"id": "2", "code": "trainer", "name": "Giảng viên"},
        }

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/10/roles", json={"role_id": "2"}, headers=headers)

        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["user_id"], "10")
        self.assertEqual(data["data"]["role"]["code"], "trainer")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.assign_role_to_user")
    def test_04_assign_duplicate_role_returns_409(self, mock_assign, mock_sess, mock_perm):
        """4. Phân vai trò đã tồn tại -> 409 DUPLICATE_ROLE_ASSIGNMENT."""
        mock_sess.return_value = self.session
        mock_assign.side_effect = UserRoleServiceError(
            code="DUPLICATE_ROLE_ASSIGNMENT",
            message="Người dùng đã được gán vai trò này trước đó.",
            status_code=409,
        )

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/10/roles", json={"role_id": "2"}, headers=headers)

        self.assertEqual(resp.status_code, 409)
        data = resp.get_json()
        self.assertEqual(data["code"], "DUPLICATE_ROLE_ASSIGNMENT")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.assign_role_to_user")
    def test_05_assign_invalid_user_returns_404(self, mock_assign, mock_sess, mock_perm):
        """5. Phân vai trò cho user không tồn tại -> 404 USER_NOT_FOUND."""
        mock_sess.return_value = self.session
        mock_assign.side_effect = UserRoleServiceError(
            code="USER_NOT_FOUND",
            message="Không tìm thấy người dùng.",
            status_code=404,
        )

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/9999/roles", json={"role_id": "2"}, headers=headers)

        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertEqual(data["code"], "USER_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.assign_role_to_user")
    def test_06_assign_invalid_role_returns_404(self, mock_assign, mock_sess, mock_perm):
        """6. Phân vai trò không tồn tại trong hệ thống -> 404 ROLE_NOT_FOUND."""
        mock_sess.return_value = self.session
        mock_assign.side_effect = UserRoleServiceError(
            code="ROLE_NOT_FOUND",
            message="Không tìm thấy vai trò hợp lệ.",
            status_code=404,
        )

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/10/roles", json={"role_id": "9999"}, headers=headers)

        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertEqual(data["code"], "ROLE_NOT_FOUND")

    # =========================================================================
    # C. REVOKE MATRIX
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.revoke_role_from_user")
    def test_07_revoke_valid_role_success(self, mock_revoke, mock_sess, mock_perm):
        """7. Gỡ vai trò khỏi người dùng thành công -> 200 OK."""
        mock_sess.return_value = self.session
        mock_revoke.return_value = {
            "user_id": "10",
            "role_id": "2",
            "role_code": "trainer",
        }

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.delete("/api/users/10/roles/2", headers=headers)

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["user_id"], "10")
        self.assertEqual(data["data"]["role_id"], "2")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.revoke_role_from_user")
    def test_08_revoke_mapping_not_found_returns_404(self, mock_revoke, mock_sess, mock_perm):
        """8. Gỡ vai trò người dùng không sở hữu -> 404 ROLE_NOT_ASSIGNED."""
        mock_sess.return_value = self.session
        mock_revoke.side_effect = UserRoleServiceError(
            code="ROLE_NOT_ASSIGNED",
            message="Người dùng không sở hữu vai trò này để gỡ bỏ.",
            status_code=404,
        )

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.delete("/api/users/10/roles/2", headers=headers)

        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertEqual(data["code"], "ROLE_NOT_ASSIGNED")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.revoke_role_from_user")
    def test_09_revoke_user_not_found_returns_404(self, mock_revoke, mock_sess, mock_perm):
        """9. Gỡ vai trò khi user không tồn tại -> 404 USER_NOT_FOUND."""
        mock_sess.return_value = self.session
        mock_revoke.side_effect = UserRoleServiceError(
            code="USER_NOT_FOUND",
            message="Không tìm thấy người dùng.",
            status_code=404,
        )

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.delete("/api/users/9999/roles/2", headers=headers)

        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertEqual(data["code"], "USER_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.revoke_role_from_user")
    def test_10_revoke_role_not_found_returns_404(self, mock_revoke, mock_sess, mock_perm):
        """10. Gỡ vai trò khi vai trò không tồn tại -> 404 ROLE_NOT_FOUND."""
        mock_sess.return_value = self.session
        mock_revoke.side_effect = UserRoleServiceError(
            code="ROLE_NOT_FOUND",
            message="Không tìm thấy vai trò hợp lệ.",
            status_code=404,
        )

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.delete("/api/users/10/roles/9999", headers=headers)

        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertEqual(data["code"], "ROLE_NOT_FOUND")

    # =========================================================================
    # D. SECURITY MATRIX
    # =========================================================================

    def test_11_security_unauthenticated_returns_401(self):
        """11. Chưa xác thực (thiếu token) -> 401 UNAUTHORIZED."""
        resp1 = self.client.get("/api/users/10/roles")
        self.assertEqual(resp1.status_code, 401)

        resp2 = self.client.get("/api/roles")
        self.assertEqual(resp2.status_code, 401)

        resp3 = self.client.post("/api/users/10/roles", json={"role_id": "2"})
        self.assertEqual(resp3.status_code, 401)

        resp4 = self.client.delete("/api/users/10/roles/2")
        self.assertEqual(resp4.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission", return_value=False)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_12_security_forbidden_returns_403(self, mock_sess, mock_perm):
        """12. Đã đăng nhập nhưng không đủ quyền -> 403 FORBIDDEN."""
        unprev_sess = LoginSession(
            session_id="unprivileged-session-102",
            user_id="unprivileged-user-102",
            refresh_jti="ref-jti-unp-102",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )
        mock_sess.return_value = unprev_sess

        headers = {"Authorization": f"Bearer {self.unprivileged_token}"}

        resp1 = self.client.get("/api/users/10/roles", headers=headers)
        self.assertEqual(resp1.status_code, 403)
        self.assertEqual(resp1.get_json()["code"], "FORBIDDEN")

        resp2 = self.client.post("/api/users/10/roles", json={"role_id": "2"}, headers=headers)
        self.assertEqual(resp2.status_code, 403)
        self.assertEqual(resp2.get_json()["code"], "FORBIDDEN")

        resp3 = self.client.delete("/api/users/10/roles/2", headers=headers)
        self.assertEqual(resp3.status_code, 403)
        self.assertEqual(resp3.get_json()["code"], "FORBIDDEN")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.get_user_roles")
    def test_13_security_authorized_success(self, mock_get_roles, mock_sess, mock_perm):
        """13. Có đầy đủ quyền (user.view / user.manage) -> Thành công."""
        mock_sess.return_value = self.session
        mock_get_roles.return_value = {
            "user_id": "10",
            "roles": [{"id": "2", "code": "trainer", "name": "Giảng viên"}],
        }

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.get("/api/users/10/roles", headers=headers)
        self.assertEqual(resp.status_code, 200)

    @patch("app.utils.rbac_auth.has_permission", return_value=False)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_14_security_default_deny(self, mock_sess, mock_perm):
        """14. Nguyên tắc default deny: quyền không tồn tại hoặc không được cấp rõ ràng -> Mặc định từ chối 403."""
        mock_sess.return_value = self.session

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.get("/api/users/10/roles", headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "FORBIDDEN")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.get_user_roles")
    def test_15_security_sql_injection_payload_treated_as_data(self, mock_get_roles, mock_sess, mock_perm):
        """15. Payload SQL injection trong URL / Body được xử lý an toàn dạng text, không gây lỗi cú pháp SQL."""
        mock_sess.return_value = self.session
        mock_get_roles.side_effect = UserRoleServiceError(
            code="USER_NOT_FOUND",
            message="Không tìm thấy người dùng.",
            status_code=404,
        )

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        sqli_user = "1' OR '1'='1"
        resp = self.client.get(f"/api/users/{sqli_user}/roles", headers=headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["code"], "USER_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.get_user_roles")
    @patch("app.services.user_role_service.get_available_roles")
    def test_16_security_no_sensitive_data_leakage(self, mock_avail_roles, mock_get_roles, mock_sess, mock_perm):
        """16. Response API không chứa password hash, salt, query DB internals hay token nhạy cảm."""
        mock_sess.return_value = self.session
        mock_get_roles.return_value = {
            "user_id": "10",
            "roles": [{"id": "2", "code": "trainer", "name": "Giảng viên"}],
        }
        mock_avail_roles.return_value = [
            {"id": "2", "code": "trainer", "name": "Giảng viên"}
        ]

        headers = {"Authorization": f"Bearer {self.admin_token}"}

        resp1 = self.client.get("/api/users/10/roles", headers=headers)
        resp1_text = resp1.get_data(as_text=True)
        self.assertNotIn("password_hash", resp1_text)
        self.assertNotIn("supersecretsalthashvalue", resp1_text)

        resp2 = self.client.get("/api/roles", headers=headers)
        resp2_text = resp2.get_data(as_text=True)
        self.assertNotIn("password", resp2_text)
        self.assertNotIn("permission_ids", resp2_text)


if __name__ == "__main__":
    unittest.main()
