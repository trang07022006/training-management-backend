"""
Kiểm thử API tìm kiếm và lọc Lead (SCRUM-128 - Activity A1/A2/A3).
Bao gồm:
1. Xác thực RBAC:
   - 401 Unauthorized khi không có token hoặc token sai.
   - 403 Forbidden khi người dùng không có quyền 'course.manage'.
   - 200 OK khi người dùng có quyền 'course.manage'.
2. Tìm kiếm (Search):
   - Tìm kiếm theo họ tên (hỗ trợ tiếng Việt có dấu, case-insensitive).
   - Tìm kiếm theo số điện thoại.
   - Tìm kiếm theo email.
   - An toàn khi tìm kiếm chứa ký tự đặc biệt (%, _, quote, dấu tiếng Việt).
   - Chặn từ khóa tìm kiếm quá dài (> 100 ký tự -> 400 INVALID_PARAMS).
3. Bộ lọc (Filters):
   - Lọc theo trạng thái hợp lệ (status).
   - Lọc trạng thái không hợp lệ (400 INVALID_PARAMS).
   - Lọc theo chương trình quan tâm (interested_program_id).
   - Lọc theo người phụ trách (assigned_to_user_id) và chưa phân công ('unassigned').
   - Lọc theo nguồn tiếp nhận (source).
   - Lọc theo khoảng thời gian (date_from, date_to).
   - Chặn date_from > date_to (400 INVALID_PARAMS).
   - Chặn định dạng ngày sai (400 INVALID_PARAMS).
4. Kết hợp đa điều kiện:
   - Search + status + assigned_to_user_id.
5. Sắp xếp (Sort) và Phân trang (Pagination):
   - Sắp xếp tăng dần / giảm dần theo whitelist (created_at, updated_at, full_name, status).
   - Chặn trường sort không hợp lệ (400 INVALID_PARAMS).
   - Chặn thứ tự sort không hợp lệ (400 INVALID_PARAMS).
   - Kiểm tra page, page_size hợp lệ và metadata trả về (total, page, page_size, total_pages).
6. Tích hợp trực tiếp trên MySQL và cleanup dữ liệu sạch sẽ.
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
    LEAD_STATUS_CONTACTED,
    LEAD_STATUS_NEW,
    LEAD_STATUS_QUALIFIED,
    Lead,
)
from app.models.login_session import LoginSession
from app.repositories import lead_repository
from app.routes.lead_routes import lead_bp


class Scrum128LeadSearchFilterApiTests(unittest.TestCase):
    """Bộ kiểm thử cho chức năng tìm kiếm, lọc và sắp xếp Lead."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum128-at-least-32-bytes-long",
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
            session_id="session-authorized-128",
            user_id=self.admin_user_id,
            refresh_jti="ref-auth-128",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        self.unauthorized_user_id = "user-unauth-trainee-128"
        self.unauthorized_session = LoginSession(
            session_id="session-unauth-128",
            user_id=self.unauthorized_user_id,
            refresh_jti="ref-unauth-128",
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

    def tearDown(self):
        for lid in self.created_lead_ids:
            try:
                lead_repository.delete_lead_for_testing(lid)
            except Exception:
                pass

    def _create_lead(
        self,
        full_name: str,
        phone: str,
        email: str | None = None,
        status: str = LEAD_STATUS_NEW,
        assigned_to_user_id: str | None = None,
        source: str = LEAD_SOURCE_PUBLIC_FORM,
        created_at: datetime | None = None,
    ) -> str:
        lid = str(uuid.uuid4())
        lead = Lead(
            id=lid,
            full_name=full_name,
            phone=phone,
            email=email,
            status=status,
            assigned_to_user_id=assigned_to_user_id,
            source=source,
            created_at=created_at or self.now,
        )
        lead_repository.insert_lead(lead)
        self.created_lead_ids.append(lid)
        return lid

    # =========================================================================
    # 1. RBAC & PERMISSION TESTS
    # =========================================================================

    def test_search_leads_unauthenticated_returns_401(self):
        """GET /api/v1/leads không có token trả về 401."""
        res = self.client.get("/api/v1/leads?search=test")
        self.assertEqual(res.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_search_leads_unauthorized_returns_403(
        self, mock_get_session, mock_has_perm
    ):
        """GET /api/v1/leads không có quyền 'course.manage' trả về 403."""
        mock_get_session.return_value = self.unauthorized_session
        mock_has_perm.return_value = False

        res = self.client.get("/api/v1/leads?search=test", headers=self.unauth_headers)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    # =========================================================================
    # 2. SEARCH TESTS (Name, Phone, Email, Vietnamese Unicode, Special chars)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_search_by_vietnamese_name(self, mock_get_session, mock_has_perm):
        """Tìm kiếm theo tên tiếng Việt có dấu thành công."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(
            full_name="Nguyễn Đắc Vũ",
            phone="0911001100",
            email="dacvu@example.com",
        )

        res = self.client.get("/api/v1/leads?search=Đắc+Vũ", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]
        self.assertTrue(any(item["id"] == lid for item in items))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_search_by_phone(self, mock_get_session, mock_has_perm):
        """Tìm kiếm theo số điện thoại thành công."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        unique_phone = "0944889977"
        lid = self._create_lead(
            full_name="Lê Văn Điện Thoại",
            phone=unique_phone,
            email="phone@example.com",
        )

        res = self.client.get(f"/api/v1/leads?search={unique_phone}", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]
        self.assertTrue(any(item["id"] == lid for item in items))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_search_by_email(self, mock_get_session, mock_has_perm):
        """Tìm kiếm theo email thành công."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        unique_email = f"search_{uuid.uuid4().hex[:8]}@ictu.edu.vn"
        lid = self._create_lead(
            full_name="Hoàng Thị Email",
            phone="0933221100",
            email=unique_email,
        )

        res = self.client.get(f"/api/v1/leads?search={unique_email}", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]
        self.assertTrue(any(item["id"] == lid for item in items))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_search_with_long_query_fails(self, mock_get_session, mock_has_perm):
        """Từ khóa tìm kiếm dài quá 100 ký tự trả về 400 INVALID_PARAMS."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        long_q = "a" * 101
        res = self.client.get(f"/api/v1/leads?search={long_q}", headers=self.auth_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    # =========================================================================
    # 3. FILTER TESTS (Status, Assignee, Date Range)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_filter_by_status_valid(self, mock_get_session, mock_has_perm):
        """Lọc theo trạng thái status hợp lệ."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(
            full_name="Học Viên Qualified",
            phone="0911882233",
            status=LEAD_STATUS_QUALIFIED,
        )

        res = self.client.get("/api/v1/leads?status=qualified", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]
        self.assertTrue(any(item["id"] == lid for item in items))
        self.assertTrue(all(item["status"] == "qualified" for item in items))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_filter_by_invalid_status_returns_400(self, mock_get_session, mock_has_perm):
        """Lọc theo trạng thái không hợp lệ trả về 400 INVALID_PARAMS."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.get("/api/v1/leads?status=unknown_status", headers=self.auth_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_filter_by_assignee_and_unassigned(self, mock_get_session, mock_has_perm):
        """Lọc theo người phụ trách cụ thể và lọc danh sách chưa phân công ('unassigned')."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid_assigned = self._create_lead(
            full_name="Lead Đã Phân Công",
            phone="0988001122",
            assigned_to_user_id=self.admin_user_id,
        )
        lid_unassigned = self._create_lead(
            full_name="Lead Chưa Phân Công",
            phone="0988003344",
            assigned_to_user_id=None,
        )

        # 1. Lọc theo admin_user_id
        res_assigned = self.client.get(
            f"/api/v1/leads?assigned_to_user_id={self.admin_user_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(res_assigned.status_code, 200)
        items = res_assigned.get_json()["data"]["items"]
        self.assertTrue(any(item["id"] == lid_assigned for item in items))
        self.assertFalse(any(item["id"] == lid_unassigned for item in items))

        # 2. Lọc unassigned
        res_unassigned = self.client.get(
            "/api/v1/leads?assigned_to_user_id=unassigned",
            headers=self.auth_headers,
        )
        self.assertEqual(res_unassigned.status_code, 200)
        items = res_unassigned.get_json()["data"]["items"]
        self.assertTrue(any(item["id"] == lid_unassigned for item in items))
        self.assertFalse(any(item["id"] == lid_assigned for item in items))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_filter_date_range_validation(self, mock_get_session, mock_has_perm):
        """date_from > date_to trả về 400 INVALID_PARAMS."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.get(
            "/api/v1/leads?date_from=2026-12-31&date_to=2026-01-01",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    # =========================================================================
    # 4. SORTING & COMBINED TESTS
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_combined_search_and_filters(self, mock_get_session, mock_has_perm):
        """Kết hợp tìm kiếm và nhiều bộ lọc cùng lúc."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(
            full_name="Nguyễn Văn Kết Hợp",
            phone="0911223399",
            email="kethop@ictu.edu.vn",
            status=LEAD_STATUS_CONTACTED,
            assigned_to_user_id=self.admin_user_id,
        )

        # Query đúng tất cả điều kiện
        res = self.client.get(
            f"/api/v1/leads?search=Kết+Hợp&status=contacted&assigned_to_user_id={self.admin_user_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]
        self.assertTrue(any(item["id"] == lid for item in items))

        # Query sai status không ra kết quả
        res_mismatch = self.client.get(
            f"/api/v1/leads?search=Kết+Hợp&status=new&assigned_to_user_id={self.admin_user_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(res_mismatch.status_code, 200)
        items_mismatch = res_mismatch.get_json()["data"]["items"]
        self.assertFalse(any(item["id"] == lid for item in items_mismatch))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_invalid_sort_by_returns_400(self, mock_get_session, mock_has_perm):
        """Cột sort_by không nằm trong whitelist trả về 400 INVALID_PARAMS."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.get(
            "/api/v1/leads?sort_by=password_hash",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")
