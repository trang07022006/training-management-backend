"""
Kiểm thử API cập nhật trạng thái Lead (SCRUM-126 - Activity A3).
Bao gồm:
1. Xác thực RBAC:
   - 401 Unauthorized khi không có token.
   - 403 Forbidden khi người dùng không có quyền 'course.manage'.
   - 200 OK khi người dùng có quyền 'course.manage'.
2. Ràng buộc trường cập nhật (Hardening):
   - Chặn các trường hệ thống và không được phép (id, created_at, source, phone, email, ...).
   - Kiểm tra định dạng JSON và UUID.
3. Kiểm tra tính hợp lệ của trạng thái:
   - new, contacted, qualified, converted, lost, cancelled.
   - Báo lỗi 400 INVALID_STATUS khi truyền trạng thái không hợp lệ.
4. Xử lý trường hợp Lead không tồn tại (404 LEAD_NOT_FOUND).
5. Kiểm thử tích hợp trực tiếp trên MySQL (Live Test) và dọn dẹp dữ liệu.
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
    LEAD_STATUS_CONTACTED,
    LEAD_STATUS_CONVERTED,
    LEAD_STATUS_LOST,
    LEAD_STATUS_NEW,
    LEAD_STATUS_QUALIFIED,
    Lead,
)
from app.models.login_session import LoginSession
from app.repositories import lead_repository
from app.routes.lead_routes import lead_bp


class Scrum126LeadUpdateApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật cho API cập nhật trạng thái Lead."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum126-update-api-secret",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(lead_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        self.authorized_user_id = "user-auth-course-manage"
        self.authorized_session = LoginSession(
            session_id="session-authorized-126-upd",
            user_id=self.authorized_user_id,
            refresh_jti="ref-auth-126-upd",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        self.unauthorized_user_id = "user-unauth-trainee"
        self.unauthorized_session = LoginSession(
            session_id="session-unauth-126-upd",
            user_id=self.unauthorized_user_id,
            refresh_jti="ref-unauth-126-upd",
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

    def test_01_update_status_unauthenticated_returns_401(self):
        valid_uuid = str(uuid.uuid4())
        res = self.client.patch(
            f"/api/v1/leads/{valid_uuid}",
            json={"status": "contacted"},
        )
        self.assertEqual(res.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_update_status_unauthorized_returns_403(
        self, mock_get_session, mock_has_perm
    ):
        valid_uuid = str(uuid.uuid4())
        mock_get_session.return_value = self.unauthorized_session
        mock_has_perm.return_value = False

        res = self.client.patch(
            f"/api/v1/leads/{valid_uuid}",
            headers=self.unauth_headers,
            json={"status": "contacted"},
        )
        self.assertEqual(res.status_code, 403)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_03_update_status_invalid_uuid_returns_400(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.patch(
            "/api/v1/leads/bad-uuid",
            headers=self.auth_headers,
            json={"status": "contacted"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_04_update_status_disallowed_fields_returns_400(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True
        valid_uuid = str(uuid.uuid4())

        res = self.client.patch(
            f"/api/v1/leads/{valid_uuid}",
            headers=self.auth_headers,
            json={"status": "contacted", "source": "admin_hacked", "id": "fake"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_05_update_status_invalid_status_returns_400(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True
        valid_uuid = str(uuid.uuid4())

        res = self.client.patch(
            f"/api/v1/leads/{valid_uuid}",
            headers=self.auth_headers,
            json={"status": "unsupported_xyz"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_STATUS")

    @patch("app.repositories.lead_repository.get_lead_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_06_update_status_lead_not_found_returns_404(
        self, mock_get_session, mock_has_perm, mock_get
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get.return_value = None
        valid_uuid = str(uuid.uuid4())

        res = self.client.patch(
            f"/api/v1/leads/{valid_uuid}",
            headers=self.auth_headers,
            json={"status": "contacted"},
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "LEAD_NOT_FOUND")

    @patch("app.repositories.lead_repository.update_lead_status")
    @patch("app.repositories.lead_repository.get_lead_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_07_update_status_success(
        self, mock_get_session, mock_has_perm, mock_get, mock_update
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lead_id = str(uuid.uuid4())
        existing = Lead(
            id=lead_id,
            full_name="Nguyễn Văn A",
            phone="0911223344",
            status=LEAD_STATUS_NEW,
            created_at=self.now,
            updated_at=self.now,
        )
        updated = Lead(
            id=lead_id,
            full_name="Nguyễn Văn A",
            phone="0911223344",
            status=LEAD_STATUS_QUALIFIED,
            created_at=self.now,
            updated_at=datetime.now(timezone.utc),
        )

        mock_get.return_value = existing
        mock_update.return_value = updated

        res = self.client.patch(
            f"/api/v1/leads/{lead_id}",
            headers=self.auth_headers,
            json={"status": "qualified"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["status"], "qualified")


class Scrum126LeadUpdateApiLiveTests(unittest.TestCase):
    """Kiểm thử cập nhật trạng thái trực tiếp trên MySQL."""

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

    def test_live_update_lead_status(self):
        lead_id = str(uuid.uuid4())
        self.created_lead_ids.append(lead_id)

        lead = Lead(
            id=lead_id,
            full_name="Live Update Lead Test",
            phone="0988001122",
            status=LEAD_STATUS_NEW,
        )
        lead_repository.insert_lead(lead)

        # Cập nhật status qua service
        from app.services.lead_service import update_lead_status_service
        result = update_lead_status_service(lead_id, {"status": "contacted"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["status"], "contacted")

        # Kiểm tra đọc lại từ DB
        db_lead = lead_repository.get_lead_by_id(lead_id)
        self.assertIsNotNone(db_lead)
        self.assertEqual(db_lead.status, "contacted")
