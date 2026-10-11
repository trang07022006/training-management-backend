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
            json={"user_id": "4fae5ce7-f236-443e-a93a-778db2b0e1bf"},
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
            json={"user_id": "4fae5ce7-f236-443e-a93a-778db2b0e1bf"},
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
            json={"user_id": "4fae5ce7-f236-443e-a93a-778db2b0e1bf", "extra_field": "hack"},
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
                    (inactive_uid, "Cán bộ Khóa", f"locked_{inactive_uid[:8]}@ictu.edu.vn", "hash", "consultant", "inactive"),
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
        """Không được phép phân công cho user có role trainer/trainee/admin/user/training_manager (SCRUM-127)."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_test_lead()
        # Thử với role trainer
        trainer_uid = "7c50e76d-7c00-4167-b5dd-1c06df11d3e8"  # Nguyễn Văn A (trainer)
        res = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": trainer_uid},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_ASSIGNEE")
        self.assertEqual(
            res.get_json()["message"],
            "Chỉ có thể phân công Lead cho nhân viên Tư vấn tuyển sinh.",
        )

        # Thử với role training_manager
        tm_uid = "ebcf9c67-0cd9-4199-a0ef-35541879f25d"  # QA Quản lý đào tạo
        res2 = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": tm_uid},
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "INVALID_ASSIGNEE")

    # =========================================================================
    # 3. SUCCESSFUL ASSIGN & UNASSIGN & HISTORY TESTS
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_assign_lead_success(
        self, mock_get_session, mock_has_perm
    ):
        """Phân công Lead cho tư vấn viên hợp lệ thành công (SCRUM-127)."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_test_lead()
        consultant_id = "4fae5ce7-f236-443e-a93a-778db2b0e1bf"  # test (consultant)
        res = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": consultant_id},
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["data"]["assigned_to_user_id"], consultant_id)
        self.assertIsNotNone(body["data"]["assigned_at"])
        self.assertEqual(body["data"]["assigned_to_name"], "test")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_transfer_lead_and_verify_history(
        self, mock_get_session, mock_has_perm
    ):
        """Chuyển giao Lead từ Consultant A sang Consultant B rồi Unassign và kiểm tra lịch sử (SCRUM-127)."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_test_lead()
        consultant_a = "4fae5ce7-f236-443e-a93a-778db2b0e1bf"  # test
        consultant_b = "b98111a5-6303-4de9-be69-e3059c5796a6"  # QA Tư vấn tuyển sinh

        # 1. Gán lần 1: None -> Consultant A
        res1 = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": consultant_a},
        )
        self.assertEqual(res1.status_code, 200)

        # 2. Chuyển giao: Consultant A -> Consultant B
        res2 = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": consultant_b},
        )
        self.assertEqual(res2.status_code, 200)

        # 3. Gỡ phân công: Consultant B -> None
        res3 = self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": None},
        )
        self.assertEqual(res3.status_code, 200)

        # 4. Lấy lịch sử qua API GET /api/v1/leads/<id>/history
        res_hist = self.client.get(
            f"/api/v1/leads/{lid}/history",
            headers=self.auth_headers,
        )
        self.assertEqual(res_hist.status_code, 200)
        history = res_hist.get_json()["data"]
        self.assertEqual(len(history), 3)

        # Bản ghi mới nhất (index 0): Consultant B -> None
        self.assertEqual(history[0]["old_assigned_to_user_id"], consultant_b)
        self.assertIsNone(history[0]["new_assigned_to_user_id"])

        # Bản ghi thứ hai (index 1): Consultant A -> Consultant B
        self.assertEqual(history[1]["old_assigned_to_user_id"], consultant_a)
        self.assertEqual(history[1]["new_assigned_to_user_id"], consultant_b)
        self.assertEqual(history[1]["old_assigned_to_name"], "test")

        # Bản ghi đầu tiên (index 2): None -> Consultant A
        self.assertIsNone(history[2]["old_assigned_to_user_id"])
        self.assertEqual(history[2]["new_assigned_to_user_id"], consultant_a)
        self.assertEqual(history[2]["new_assigned_to_name"], "test")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_unassign_lead_via_delete_endpoint(
        self, mock_get_session, mock_has_perm
    ):
        """Gỡ phân công Lead bằng DELETE /api/v1/leads/<id>/assignment thành công."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_test_lead()
        consultant_id = "4fae5ce7-f236-443e-a93a-778db2b0e1bf"
        # Bước 1: Assign
        self.client.patch(
            f"/api/v1/leads/{lid}/assignment",
            headers=self.auth_headers,
            json={"user_id": consultant_id},
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
    # 4. ASSIGNABLE USERS LIST TESTS (CONSULTANTS ONLY)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_get_assignable_users_returns_consultants_only(
        self, mock_get_session, mock_has_perm
    ):
        """GET /api/v1/leads/assignable-users CHỈ trả về tài khoản Tư vấn tuyển sinh (SCRUM-127)."""
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
            self.assertEqual(u["role"], "consultant")
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

    # =========================================================================
    # 5. BULK ASSIGNMENT TESTS (SCRUM-127)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_bulk_assign_leads_success(
        self, mock_get_session, mock_has_perm
    ):
        """POST /api/v1/leads/bulk-assignment phân công nhiều Lead thành công (SCRUM-127)."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid1 = self._create_test_lead()
        lid2 = self._create_test_lead()
        consultant_id = "4fae5ce7-f236-443e-a93a-778db2b0e1bf"

        res = self.client.post(
            "/api/v1/leads/bulk-assignment",
            headers=self.auth_headers,
            json={
                "lead_ids": [lid1, lid2],
                "user_id": consultant_id,
            },
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["data"]["updated_count"], 2)

        # Kiểm tra cả 2 lead đã được phân công cho consultant
        lead1 = lead_repository.get_lead_by_id(lid1)
        lead2 = lead_repository.get_lead_by_id(lid2)
        self.assertEqual(lead1.assigned_to_user_id, consultant_id)
        self.assertEqual(lead2.assigned_to_user_id, consultant_id)

    # =========================================================================
    # 6. CONSULTANT DATA SCOPING TESTS (SCRUM-127)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_consultant_only_sees_assigned_leads(
        self, mock_get_session, mock_has_perm
    ):
        """Tư vấn tuyển sinh đăng nhập CHỈ nhìn thấy Lead được giao cho mình (SCRUM-127)."""
        consultant_a = "4fae5ce7-f236-443e-a93a-778db2b0e1bf"  # test
        consultant_b = "b98111a5-6303-4de9-be69-e3059c5796a6"  # QA Tư vấn tuyển sinh

        session_consultant_a = LoginSession(
            session_id="session-consultant-a-127",
            user_id=consultant_a,
            refresh_jti="ref-ca-127",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        with self.app.app_context():
            token_ca = create_access_token(
                identity=consultant_a,
                additional_claims={"sid": session_consultant_a.session_id},
            )
        headers_ca = {"Authorization": f"Bearer {token_ca}"}

        mock_get_session.return_value = session_consultant_a
        mock_has_perm.return_value = True

        lid_a = self._create_test_lead()
        lid_b = self._create_test_lead()

        # Gán lead A cho consultant A, lead B cho consultant B
        lead_repository.assign_lead(lid_a, consultant_a)
        lead_repository.assign_lead(lid_b, consultant_b)

        # Consultant A gọi list leads
        res = self.client.get(
            "/api/v1/leads",
            headers=headers_ca,
        )
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]
        item_ids = [it["id"] for it in items]

        self.assertIn(lid_a, item_ids)
        self.assertNotIn(lid_b, item_ids)


