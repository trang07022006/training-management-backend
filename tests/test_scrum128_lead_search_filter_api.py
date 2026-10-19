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
    LEAD_SOURCE_DIRECT,
    LEAD_SOURCE_HOTLINE,
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_SOURCE_SOCIAL,
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

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_filter_by_source_valid_and_invalid(self, mock_get_session, mock_has_perm):
        """TC128-04: Lọc theo nguồn (source) hợp lệ và chặn nguồn không hợp lệ."""
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid_direct = self._create_lead(
            full_name="Nguyễn Nguồn Trực Tiếp",
            phone="0988111222",
            source=LEAD_SOURCE_DIRECT,
        )
        lid_public = self._create_lead(
            full_name="Lê Nguồn Website",
            phone="0988333444",
            source=LEAD_SOURCE_PUBLIC_FORM,
        )
        lid_social = self._create_lead(
            full_name="Trần Nguồn Mạng Xã Hội",
            phone="0988555666",
            source=LEAD_SOURCE_SOCIAL,
        )

        # 1. Lọc theo source=direct
        res_direct = self.client.get(
            f"/api/v1/leads?source={LEAD_SOURCE_DIRECT}",
            headers=self.auth_headers,
        )
        self.assertEqual(res_direct.status_code, 200)
        items_direct = res_direct.get_json()["data"]["items"]
        self.assertTrue(any(i["id"] == lid_direct for i in items_direct))
        self.assertFalse(any(i["id"] == lid_public for i in items_direct))
        self.assertFalse(any(i["id"] == lid_social for i in items_direct))

        # 2. Lọc theo source=social
        res_social = self.client.get(
            f"/api/v1/leads?source={LEAD_SOURCE_SOCIAL}",
            headers=self.auth_headers,
        )
        self.assertEqual(res_social.status_code, 200)
        items_social = res_social.get_json()["data"]["items"]
        self.assertTrue(any(i["id"] == lid_social for i in items_social))
        self.assertFalse(any(i["id"] == lid_direct for i in items_social))
        self.assertFalse(any(i["id"] == lid_public for i in items_social))

        # 3. Lọc theo nguồn không hợp lệ -> 400 INVALID_PARAMS
        res_invalid = self.client.get(
            "/api/v1/leads?source=invalid_source_code",
            headers=self.auth_headers,
        )
        self.assertEqual(res_invalid.status_code, 400)
        self.assertEqual(res_invalid.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_filter_date_range_timezone_same_day_no_leak(
        self, mock_get_session, mock_has_perm
    ):
        """
        TC128-06 & TC128-07: Lọc cùng ngày 10/10/2026 -> 10/10/2026 theo múi giờ Việt Nam GMT+7.
        - Lead A: tạo lúc 10/10/2026 01:27 GMT+7 (09/10/2026 18:27 UTC) -> PHẢI CÓ
        - Lead B: tạo lúc 10/10/2026 23:45 GMT+7 (10/10/2026 16:45 UTC) -> PHẢI CÓ
        - Lead C: tạo lúc 11/10/2026 01:27 GMT+7 (10/10/2026 18:27 UTC) -> KHÔNG ĐƯỢC CÓ (Next-day leak test)
        - Lead D: tạo lúc 09/10/2026 23:30 GMT+7 (09/10/2026 16:30 UTC) -> KHÔNG ĐƯỢC CÓ (Previous-day leak test)
        """
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid_a = self._create_lead(
            full_name="Lead A Ngày 10 Sáng",
            phone="0977000001",
            created_at=datetime(2026, 10, 9, 18, 27, 0, tzinfo=timezone.utc),
        )
        lid_b = self._create_lead(
            full_name="Lead B Ngày 10 Đêm",
            phone="0977000002",
            created_at=datetime(2026, 10, 10, 16, 45, 0, tzinfo=timezone.utc),
        )
        lid_c = self._create_lead(
            full_name="Lead C Ngày 11 Rạng Sáng",
            phone="0977000003",
            created_at=datetime(2026, 10, 10, 18, 27, 0, tzinfo=timezone.utc),
        )
        lid_d = self._create_lead(
            full_name="Lead D Ngày 09 Đêm",
            phone="0977000004",
            created_at=datetime(2026, 10, 9, 16, 30, 0, tzinfo=timezone.utc),
        )

        res = self.client.get(
            "/api/v1/leads?date_from=2026-10-10&date_to=2026-10-10",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]

        self.assertTrue(any(i["id"] == lid_a for i in items), "Lead A (10/10 01:27 GMT+7) phải có")
        self.assertTrue(any(i["id"] == lid_b for i in items), "Lead B (10/10 23:45 GMT+7) phải có")
        self.assertFalse(any(i["id"] == lid_c for i in items), "Lead C (11/10 01:27 GMT+7) KHÔNG được xuất hiện!")
        self.assertFalse(any(i["id"] == lid_d for i in items), "Lead D (09/10 23:30 GMT+7) KHÔNG được xuất hiện!")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_filter_date_range_cross_day_no_leak(
        self, mock_get_session, mock_has_perm
    ):
        """
        TC128-06: Lọc khoảng ngày 08/10/2026 -> 10/10/2026 theo múi giờ Việt Nam.
        - Lead 08/10: PHẢI CÓ
        - Lead 10/10: PHẢI CÓ
        - Lead 11/10 (01:27 GMT+7): KHÔNG ĐƯỢC CÓ
        """
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid_08 = self._create_lead(
            full_name="Lead Ngày 08",
            phone="0977080808",
            created_at=datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc),
        )
        lid_10 = self._create_lead(
            full_name="Lead Ngày 10",
            phone="0977101010",
            created_at=datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc),
        )
        lid_11 = self._create_lead(
            full_name="Lead Ngày 11 Rạng Sáng",
            phone="0977111111",
            created_at=datetime(2026, 10, 10, 18, 27, 0, tzinfo=timezone.utc),
        )

        res = self.client.get(
            "/api/v1/leads?date_from=2026-10-08&date_to=2026-10-10",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]

        self.assertTrue(any(i["id"] == lid_08 for i in items))
        self.assertTrue(any(i["id"] == lid_10 for i in items))
        self.assertFalse(any(i["id"] == lid_11 for i in items), "Lead ngày 11/10 không được lọt vào filter đến ngày 10/10!")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_filter_date_single_boundary_and_aliases(
        self, mock_get_session, mock_has_perm
    ):
        """
        TC128-06: Lọc chỉ có from_date hoặc chỉ có to_date, hỗ trợ alias from_date/to_date.
        """
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid_old = self._create_lead(
            full_name="Lead Cũ Ngày 09",
            phone="0977090909",
            created_at=datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc),
        )
        lid_new = self._create_lead(
            full_name="Lead Mới Ngày 11",
            phone="0977110011",
            created_at=datetime(2026, 10, 10, 18, 30, 0, tzinfo=timezone.utc), # 11/10 01:30 GMT+7
        )

        # 1. Chỉ có from_date=2026-10-11
        res_from = self.client.get(
            "/api/v1/leads?from_date=2026-10-11&sort_order=ASC&page_size=100",
            headers=self.auth_headers,
        )
        self.assertEqual(res_from.status_code, 200)
        items_from = res_from.get_json()["data"]["items"]
        self.assertTrue(any(i["id"] == lid_new for i in items_from))
        self.assertFalse(any(i["id"] == lid_old for i in items_from))

        # 2. Chỉ có to_date=2026-10-10
        res_to = self.client.get(
            "/api/v1/leads?to_date=2026-10-10",
            headers=self.auth_headers,
        )
        self.assertEqual(res_to.status_code, 200)
        items_to = res_to.get_json()["data"]["items"]
        self.assertTrue(any(i["id"] == lid_old for i in items_to))
        self.assertFalse(any(i["id"] == lid_new for i in items_to))

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
            full_name="Nguyễn Văn Kết Hợp QA-S127",
            phone="0911223399",
            email="kethop@ictu.edu.vn",
            status=LEAD_STATUS_CONTACTED,
            source=LEAD_SOURCE_DIRECT,
            assigned_to_user_id=self.admin_user_id,
            created_at=datetime(2026, 10, 11, 4, 30, 0, tzinfo=timezone.utc), # 11/10 11:30 GMT+7
        )

        # Query đúng tất cả điều kiện: search + status + source + assignee + date range
        res = self.client.get(
            f"/api/v1/leads?search=QA-S127&status=contacted&source=direct&assigned_to_user_id={self.admin_user_id}&date_from=2026-10-11&date_to=2026-10-11",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]
        self.assertTrue(any(item["id"] == lid for item in items))

        # Query sai source không ra kết quả
        res_source_mismatch = self.client.get(
            f"/api/v1/leads?search=QA-S127&status=contacted&source=social&assigned_to_user_id={self.admin_user_id}&date_from=2026-10-11&date_to=2026-10-11",
            headers=self.auth_headers,
        )
        self.assertEqual(res_source_mismatch.status_code, 200)
        self.assertFalse(any(item["id"] == lid for item in res_source_mismatch.get_json()["data"]["items"]))

        # Query sai status không ra kết quả
        res_mismatch = self.client.get(
            f"/api/v1/leads?search=QA-S127&status=new&source=direct&assigned_to_user_id={self.admin_user_id}&date_from=2026-10-11&date_to=2026-10-11",
            headers=self.auth_headers,
        )
        self.assertEqual(res_mismatch.status_code, 200)
        items_mismatch = res_mismatch.get_json()["data"]["items"]
        self.assertFalse(any(item["id"] == lid for item in items_mismatch))

        # Query sai date range (lệch sang ngày khác) không ra kết quả
        res_date_mismatch = self.client.get(
            f"/api/v1/leads?search=QA-S127&status=contacted&source=direct&assigned_to_user_id={self.admin_user_id}&date_from=2026-10-10&date_to=2026-10-10",
            headers=self.auth_headers,
        )
        self.assertEqual(res_date_mismatch.status_code, 200)
        self.assertFalse(any(item["id"] == lid for item in res_date_mismatch.get_json()["data"]["items"]))

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
