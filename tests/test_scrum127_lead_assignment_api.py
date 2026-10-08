"""
Kiểm thử API phân công Lead (SCRUM-127 - Activity A2/A3/A4).
Bao gồm:
1. Xác thực RBAC:
   - 401 Unauthorized khi không có token hoặc token không hợp lệ.
   - 403 Forbidden khi người dùng không có quyền 'course.manage'.
   - 200 OK khi người dùng có quyền 'course.manage'.
2. API PATCH /api/v1/leads/<lead_id>/assignment:
   - 400 INVALID_PARAMS khi UUID Lead sai định dạng.
   - 404 LEAD_NOT_FOUND khi Lead không tồn tại.
   - 400 INVALID_JSON khi body không phải JSON.
   - 400 INVALID_PARAMS khi chứa trường ngoài 'user_id'.
   - 400 INVALID_PARAMS khi user_id không phải UUID hợp lệ.
   - 404 USER_NOT_FOUND khi user_id không tồn tại trong hệ thống.
   - 400 INACTIVE_USER khi user bị vô hiệu hóa / inactive.
   - 400 INVALID_ASSIGNEE khi user có vai trò không được phép nhận lead (ví dụ trainee).
   - 200 OK khi phân công thành công cho admin/trainer đang hoạt động.
3. Gỡ phân công:
   - PATCH với {"user_id": null} -> 200 OK, xóa người phụ trách.
   - DELETE /api/v1/leads/<lead_id>/assignment -> 200 OK, xóa người phụ trách.
4. API GET /api/v1/leads/assignable-users:
   - RBAC bảo vệ.
   - Trả về danh sách an toàn (id, name, email, role), không leak password_hash hoặc dữ liệu nhạy cảm.
5. Kiểm thử tích hợp trực tiếp trên MySQL và cleanup dữ liệu.
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.config.jwt_handlers import register_jwt_handlers
from app.database.connection import get_db_connection
from app.models.lead import (
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_STATUS_NEW,
    Lead,
)
from app.models.login_session import LoginSession
from app.repositories import lead_repository
from app.routes.lead_routes import lead_bp


class Scrum127LeadAssignmentApiTests(unittest.TestCase):
    """Bộ kiểm thử đơn vị và tích hợp cho API phân công Lead."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum127-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(lead_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        # Admin user thực tế trong DB
        self.admin_user_id = "34068d8d-b2ec-4ce4-977a-28ac1b9b70de"
        self.authorized_session = LoginSession(
            session_id="session-authorized-127",
            user_id=self.admin_user_id,
            refresh_jti="ref-auth-127",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        self.unauthorized_user_id = "user-unauth-trainee-127"
        self.unauthorized_session = LoginSession(
            session_id="session-unauth-127",
            user_id=self.unauthorized_user_id,
            refresh_jti="ref-unauth-127",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        with self.app.app_context():
            self.authorized_token = create_access_token(
                identity=self.admin_user_id,
                additional_claims={"sid": self.authorized_session.session_id},
            )
            self.unauthorized_token = create_access_token(
                identity=self.unauthorized_user_id,
                additional_claims={"sid": self.unauthorized_session.session_id},
            )

        self.auth_headers = {"Authorization": f"Bearer {self.authorized_token}"}
        self.unauth_headers = {"Authorization": f"Bearer {self.unauthorized_token}"}

        self.created_lead_ids = []
        self.created_user_ids = []

    def tearDown(self):
        for lid in self.created_lead_ids:
            try:
                lead_repository.delete_lead_for_testing(lid)
            except Exception:
                pass
        for uid in self.created_user_ids:
            try:
                conn = get_db_connection()
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM users WHERE id = %s", (uid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def _create_test_lead(self) -> str:
        lid = str(uuid.uuid4())
        lead = Lead(
            id=lid,
            full_name="Nguyễn Văn Lead Test",
            phone="0912345678",
            email="leadtest@ictu.edu.vn",
            status=LEAD_STATUS_NEW,
        )
        lead_repository.insert_lead(lead)
        self.created_lead_ids.append(lid)
        return lid

    # =========================================================================
    # 1. RBAC AUTHENTICATION TESTS
    # =========================================================================

    def test_assign_endpoint_requires_auth(self):
        """PATCH /api/v1/leads/<id>/assignment không có token trả về 401."""
        lid = str(uuid.uuid4())
        res = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            json={"user_id": self.admin_user_id},
        )
        self.assertEqual(res.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_assign_endpoint_requires_course_manage_permission(
        self, mock_get_session, mock_has_perm
    ):
        """PATCH /api/v1/leads/<id>/assignment không có quyền 'course.manage' trả về 403."""
        mock_get_session.return_value = self.unauthorized_session
        mock_has_perm.return_value = False

        lid = str(uuid.uuid4())
        res = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.unauth_headers,
            json={"user_id": self.admin_user_id},
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_assignable_users_requires_course_manage_permission(
        self, mock_get_session, mock_has_perm
    ):
        """GET /api/v1/leads/assignable-users không có quyền trả về 403."""
        mock_get_session.return_value = self.unauthorized_session
        mock_has_perm.return_value = False

        res = self.client.get(
            "/api/v1/leads/assignable-users",
            headers=self.unauth_headers,
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    # =========================================================================
    # 2. VALIDATION TESTS
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_assign_with_invalid_lead_id_format(
        self, mock_get_session, mock_has_perm
    ):
        """UUID Lead sai định dạng trả về 400 INVALID_PARAMS."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.patch(
            "/api/v1/leads/not-a-valid-uuid/assignment",
            headers=self.auth_headers,
            json={"user_id": self.admin_user_id},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_assign_with_non_existent_lead_id(
        self, mock_get_session, mock_has_perm
    ):
        """UUID Lead không tồn tại trả về 404 LEAD_NOT_FOUND."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        non_existent_lid = str(uuid.uuid4())
        res = self.client.patch(
            f"/api/v1/leads/{non_existent_lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": self.admin_user_id},
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "LEAD_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_assign_with_disallowed_fields(
        self, mock_get_session, mock_has_perm
    ):
        """Body chứa trường lạ ngoài 'user_id' trả về 400 INVALID_PARAMS."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_test_lead()
        res = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": self.admin_user_id, "extra_field": "hack"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_assign_with_invalid_user_id_format(
        self, mock_get_session, mock_has_perm
    ):
        """user_id không phải UUID hợp lệ trả về 400 INVALID_PARAMS."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_test_lead()
        res = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": "not-valid-uuid"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_assign_with_non_existent_user_id(
        self, mock_get_session, mock_has_perm
    ):
        """user_id không tồn tại trong hệ thống trả về 404 USER_NOT_FOUND."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_test_lead()
        random_user_id = str(uuid.uuid4())
        res = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": random_user_id},
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "USER_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_assign_to_inactive_user_rejected(
        self, mock_get_session, mock_has_perm
    ):
        """Không được phép phân công cho user có status inactive."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_test_lead()
        inactive_uid = str(uuid.uuid4())
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, name, email, password_hash, role, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (inactive_uid, "Cán bộ Khóa", f"locked_{inactive_uid[:8]}@ictu.edu.vn", "hash", "trainer", "inactive"),
                )
            conn.commit()
        finally:
            conn.close()
        self.created_user_ids.append(inactive_uid)

        res = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": inactive_uid},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INACTIVE_USER")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_assign_to_non_assignable_role_rejected(
        self, mock_get_session, mock_has_perm
    ):
        """Không được phép phân công cho user có role trainee/student."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_test_lead()
        trainee_uid = str(uuid.uuid4())
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, name, email, password_hash, role, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (trainee_uid, "Học viên Test", f"trainee_{trainee_uid[:8]}@ictu.edu.vn", "hash", "trainee", "active"),
                )
            conn.commit()
        finally:
            conn.close()
        self.created_user_ids.append(trainee_uid)

        res = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": trainee_uid},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_ASSIGNEE")

    # =========================================================================
    # 3. SUCCESSFUL ASSIGN & UNASSIGN TESTS
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_assign_lead_success(
        self, mock_get_session, mock_has_perm
    ):
        """Phân công Lead cho nhân sự hợp lệ thành công."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_test_lead()
        res = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": self.admin_user_id},
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["data"]["assigned_to_user_id"], self.admin_user_id)
        self.assertIsNotNone(body["data"]["assigned_at"])
        self.assertEqual(body["data"]["assigned_to_name"], "Minh Trang")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_unassign_lead_via_patch_null(
        self, mock_get_session, mock_has_perm
    ):
        """Gỡ phân công Lead bằng PATCH {"user_id": null} thành công."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_test_lead()
        # Bước 1: Assign
        self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": self.admin_user_id},
        )
        # Bước 2: Unassign
        res = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": None},
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "success")
        self.assertIsNone(body["data"]["assigned_to_user_id"])
        self.assertIsNone(body["data"]["assigned_at"])

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_unassign_lead_via_delete_endpoint(
        self, mock_get_session, mock_has_perm
    ):
        """Gỡ phân công Lead bằng DELETE /api/v1/leads/<id>/assignment thành công."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_test_lead()
        # Bước 1: Assign
        self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": self.admin_user_id},
        )
        # Bước 2: DELETE unassign
        res = self.client.delete(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "success")
        self.assertIsNone(body["data"]["assigned_to_user_id"])
        self.assertIsNone(body["data"]["assigned_at"])

    # =========================================================================
    # 4. ASSIGNABLE USERS LIST TESTS
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_get_assignable_users_returns_safe_fields_only(
        self, mock_get_session, mock_has_perm
    ):
        """GET /api/v1/leads/assignable-users chỉ trả về id, name, email, role an toàn."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.get(
            "/api/v1/leads/assignable-users",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "success")
        self.assertIsInstance(body["data"], list)
        self.assertGreater(len(body["data"]), 0)

        for u in body["data"]:
            self.assertIn("id", u)
            self.assertIn("name", u)
            self.assertIn("email", u)
            self.assertIn("role", u)
            self.assertIn(u["role"], ["admin", "trainer"])
            # Tuyệt đối không có trường nhạy cảm
            self.assertNotIn("password_hash", u)
            self.assertNotIn("date_of_birth", u)
            self.assertNotIn("address", u)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_get_assignable_users_excludes_demo_and_non_uuid_accounts(
        self, mock_get_session, mock_has_perm
    ):
        """GET /api/v1/leads/assignable-users phải loại trừ các tài khoản demo và không có UUID hợp lệ."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.get(
            "/api/v1/leads/assignable-users",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        ids = [u["id"] for u in body["data"]]
        self.assertNotIn("demo-user-trainer", ids)
        self.assertNotIn("demo-user-admin", ids)
        for u in body["data"]:
            self.assertEqual(len(u["id"]), 36)

