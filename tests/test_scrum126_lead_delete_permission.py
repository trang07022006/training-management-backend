"""
Kiểm thử quyền xóa Lead theo SCRUM-126:
- Tư vấn tuyển sinh (consultant): vào được module, xem/tạo/sửa Lead nhưng KHÔNG ĐƯỢC xóa Lead (403 FORBIDDEN).
- Quản lý đào tạo (training_manager): ĐƯỢC xóa Lead (200 OK).
- Quản trị viên (admin) và Quản lý đào tạo (training_manager) là hai vai trò khác nhau.
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.config.jwt_handlers import register_jwt_handlers
from app.models.lead import Lead, LEAD_STATUS_NEW
from app.models.login_session import LoginSession
from app.repositories import lead_repository
from app.routes.lead_routes import lead_bp


class Scrum126LeadDeletePermissionTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum126-lead-delete-permission-suite",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(lead_bp)
        self.client = self.app.test_client()

        self.now = datetime.now(timezone.utc)

        # 1. Consultant session
        self.consultant_user_id = "user-consultant-126"
        self.consultant_session = LoginSession(
            session_id="session-consultant-126",
            user_id=self.consultant_user_id,
            refresh_jti="ref-consultant-126",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        # 2. Training Manager session
        self.training_manager_user_id = "user-tm-126"
        self.training_manager_session = LoginSession(
            session_id="session-tm-126",
            user_id=self.training_manager_user_id,
            refresh_jti="ref-tm-126",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        with self.app.app_context():
            self.consultant_token = create_access_token(
                identity=self.consultant_user_id,
                additional_claims={"sid": self.consultant_session.session_id},
            )
            self.training_manager_token = create_access_token(
                identity=self.training_manager_user_id,
                additional_claims={"sid": self.training_manager_session.session_id},
            )

        self.consultant_headers = {"Authorization": f"Bearer {self.consultant_token}"}
        self.training_manager_headers = {"Authorization": f"Bearer {self.training_manager_token}"}

    def test_01_public_user_cannot_delete_lead(self):
        """Khách vãng lai chưa đăng nhập bị chặn 401."""
        res = self.client.delete(f"/api/v1/leads/{uuid.uuid4()}")
        self.assertEqual(res.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_consultant_cannot_delete_lead(self, mock_get_session, mock_has_perm):
        """
        Tư vấn tuyển sinh (consultant) KHÔNG có quyền 'lead.delete',
        yêu cầu xóa Lead bị từ chối 403 FORBIDDEN.
        """
        mock_get_session.return_value = self.consultant_session
        # Consultant có course.manage nhưng không có lead.delete
        mock_has_perm.side_effect = lambda uid, perm: (
            False if perm == "lead.delete" else True
        )

        target_lead_id = str(uuid.uuid4())
        res = self.client.delete(f"/api/v1/leads/{target_lead_id}", headers=self.consultant_headers)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json().get("code"), "FORBIDDEN")

    @patch("app.repositories.lead_repository.delete_lead")
    @patch("app.repositories.lead_repository.get_lead_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_03_training_manager_can_delete_lead(
        self, mock_get_session, mock_has_perm, mock_get_lead, mock_delete_lead
    ):
        """
        Quản lý đào tạo (training_manager) có quyền 'lead.delete',
        thực hiện xóa Lead thành công 200 OK.
        """
        mock_get_session.return_value = self.training_manager_session
        mock_has_perm.return_value = True

        target_lead_id = str(uuid.uuid4())
        mock_get_lead.return_value = Lead(
            id=target_lead_id,
            full_name="Nguyễn Văn Test Lead",
            phone="0987654321",
            status=LEAD_STATUS_NEW,
        )
        mock_delete_lead.return_value = True

        res = self.client.delete(f"/api/v1/leads/{target_lead_id}", headers=self.training_manager_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("Xóa khách hàng tiềm năng thành công", data.get("message"))


if __name__ == "__main__":
    unittest.main()
