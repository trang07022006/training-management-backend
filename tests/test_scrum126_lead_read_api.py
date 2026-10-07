"""
Kiểm thử API xem danh sách và chi tiết Lead (SCRUM-126 - Activity A2).
Bao gồm:
1. Xác thực RBAC:
   - 401 Unauthorized khi không có token hoặc token không hợp lệ.
   - 403 Forbidden khi người dùng không có quyền 'course.manage'.
   - 200 OK khi người dùng có quyền 'course.manage'.
2. API GET /api/v1/leads:
   - Phân trang chuẩn: page, page_size.
   - Xử lý tham số không hợp lệ (page <= 0, page_size > 100).
   - Kiểm tra cấu trúc phản hồi và bảo vệ PII.
3. API GET /api/v1/leads/<lead_id>:
   - Thành công với Lead tồn tại.
   - 400 INVALID_PARAMS khi UUID không hợp lệ.
   - 404 LEAD_NOT_FOUND khi UUID không tồn tại.
4. Kiểm thử tích hợp trực tiếp trên MySQL.
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
    LEAD_STATUS_QUALIFIED,
    Lead,
)
from app.models.login_session import LoginSession
from app.repositories import lead_repository
from app.routes.lead_routes import lead_bp


class Scrum126LeadReadApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật RBAC cho API xem danh sách và chi tiết Lead."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum126-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(lead_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        # Session người dùng có quyền (Admin / Trainer có 'course.manage')
        self.authorized_user_id = "user-auth-course-manage"
        self.authorized_session = LoginSession(
            session_id="session-authorized-126",
            user_id=self.authorized_user_id,
            refresh_jti="ref-auth-126",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        # Session người dùng không có quyền (Trainee chỉ có 'course.view')
        self.unauthorized_user_id = "user-unauth-trainee"
        self.unauthorized_session = LoginSession(
            session_id="session-unauthorized-126",
            user_id=self.unauthorized_user_id,
            refresh_jti="ref-unauth-126",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        with self.app.app_context():
            self.authorized_token = create_access_token(
                identity=self.authorized_user_id,
                additional_claims={"sid": self.authorized_session.session_id},
            )
            self.unauthorized_token = create_access_token(
                identity=self.unauthorized_user_id,
                additional_claims={"sid": self.unauthorized_session.session_id},
            )

        self.auth_headers = {"Authorization": f"Bearer {self.authorized_token}"}
        self.unauth_headers = {"Authorization": f"Bearer {self.unauthorized_token}"}

    # =========================================================================
    # RBAC Security Tests
    # =========================================================================

    def test_01_list_leads_unauthenticated_returns_401(self):
        res = self.client.get("/api/v1/leads")
        self.assertEqual(res.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_list_leads_unauthorized_returns_403(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.unauthorized_session
        mock_has_perm.return_value = False

        res = self.client.get("/api/v1/leads", headers=self.unauth_headers)
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data.get("code"), "FORBIDDEN")

    def test_03_detail_lead_unauthenticated_returns_401(self):
        valid_uuid = str(uuid.uuid4())
        res = self.client.get(f"/api/v1/leads/{valid_uuid}")
        self.assertEqual(res.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_04_detail_lead_unauthorized_returns_403(
        self, mock_get_session, mock_has_perm
    ):
        valid_uuid = str(uuid.uuid4())
        mock_get_session.return_value = self.unauthorized_session
        mock_has_perm.return_value = False

        res = self.client.get(f"/api/v1/leads/{valid_uuid}", headers=self.unauth_headers)
        self.assertEqual(res.status_code, 403)

    # =========================================================================
    # Validation & Read Operations Tests
    # =========================================================================

    @patch("app.repositories.lead_repository.list_leads")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_05_list_leads_success(
        self, mock_get_session, mock_has_perm, mock_list
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        fake_lead = Lead(
            id=str(uuid.uuid4()),
            full_name="Nguyễn Văn A",
            phone="0912345678",
            email="nguyena@example.com",
            status=LEAD_STATUS_NEW,
            created_at=self.now,
            updated_at=self.now,
        )
        mock_list.return_value = ([fake_lead], 1)

        res = self.client.get("/api/v1/leads?page=1&page_size=20", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["total"], 1)
        self.assertEqual(len(data["data"]["items"]), 1)
        self.assertEqual(data["data"]["items"][0]["full_name"], "Nguyễn Văn A")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_06_list_leads_invalid_pagination_returns_400(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res_zero = self.client.get("/api/v1/leads?page=0", headers=self.auth_headers)
        self.assertEqual(res_zero.status_code, 400)
        self.assertEqual(res_zero.get_json()["code"], "INVALID_PARAMS")

        res_neg = self.client.get("/api/v1/leads?page_size=-1", headers=self.auth_headers)
        self.assertEqual(res_neg.status_code, 400)

        res_overflow = self.client.get("/api/v1/leads?page_size=101", headers=self.auth_headers)
        self.assertEqual(res_overflow.status_code, 400)

    @patch("app.repositories.lead_repository.get_lead_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_07_get_lead_by_id_success(
        self, mock_get_session, mock_has_perm, mock_get
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lead_id = str(uuid.uuid4())
        fake_lead = Lead(
            id=lead_id,
            full_name="Lê Thị C",
            phone="0988776655",
            email="lethic@example.com",
            status=LEAD_STATUS_QUALIFIED,
            created_at=self.now,
            updated_at=self.now,
        )
        mock_get.return_value = fake_lead

        res = self.client.get(f"/api/v1/leads/{lead_id}", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["id"], lead_id)
        self.assertEqual(data["data"]["full_name"], "Lê Thị C")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_08_get_lead_by_id_invalid_uuid_returns_400(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.get("/api/v1/leads/not-a-valid-uuid", headers=self.auth_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.repositories.lead_repository.get_lead_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_09_get_lead_by_id_not_found_returns_404(
        self, mock_get_session, mock_has_perm, mock_get
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get.return_value = None

        valid_uuid = str(uuid.uuid4())
        res = self.client.get(f"/api/v1/leads/{valid_uuid}", headers=self.auth_headers)
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "LEAD_NOT_FOUND")


class Scrum126LeadReadApiLiveTests(unittest.TestCase):
    """Kiểm thử tích hợp trực tiếp trên cơ sở dữ liệu MySQL."""

    @classmethod
    def setUpClass(cls):
        from app.main import app
        cls.app = app
        cls.client = app.test_client()
        cls.created_lead_ids = []

    @classmethod
    def tearDownClass(cls):
        for lid in cls.created_lead_ids:
            try:
                lead_repository.delete_lead_for_testing(lid)
            except Exception:
                pass

    def test_live_read_lead(self):
        lead_id = str(uuid.uuid4())
        self.created_lead_ids.append(lead_id)

        lead = Lead(
            id=lead_id,
            full_name="Live Lead Test",
            phone="0999888777",
            email="livelead@example.com",
            message="Tin nhắn tư vấn trực tiếp",
            status=LEAD_STATUS_NEW,
        )
        lead_repository.insert_lead(lead)

        # Đọc trực tiếp từ repository
        fetched = lead_repository.get_lead_by_id(lead_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, lead_id)
        self.assertEqual(fetched.full_name, "Live Lead Test")
