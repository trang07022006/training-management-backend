from datetime import datetime, timedelta, timezone
import unittest
import uuid
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.config.jwt_handlers import register_jwt_handlers
from app.models.lead import (
    LEAD_SOURCE_DIRECT,
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_STATUS_NEW,
    Lead,
)
from app.models.login_session import LoginSession
from app.models.training_program import TrainingProgram
from app.routes.lead_routes import lead_bp


class Scrum126LeadManualCreateUpdateApiTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum126-manual-create-32b",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(lead_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        self.authorized_user_id = str(uuid.uuid4())
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

        with self.app.app_context():
            token = create_access_token(
                identity=self.authorized_user_id,
                additional_claims={"sid": "session-authorized-126"},
            )
            self.auth_headers = {"Authorization": f"Bearer {token}"}

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.lead_repository.get_lead_by_phone")
    @patch("app.repositories.lead_repository.insert_lead")
    def test_01_create_lead_success(
        self, mock_insert, mock_get_phone, mock_get_prog, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_phone.return_value = None

        prog_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(
            id=prog_id,
            code="SE-01",
            name="Kỹ thuật phần mềm",
            description=None,
            duration_semesters=8,
            standard_tuition_fee=None,
            status="active",
            created_at=None,
            updated_at=None,
        )

        created_lead = Lead(
            id=str(uuid.uuid4()),
            full_name="QA SCRUM 126",
            phone="0912612626",
            email="qa.s126@example.com",
            interested_program_id=prog_id,
            source=LEAD_SOURCE_DIRECT,
            status=LEAD_STATUS_NEW,
        )
        mock_insert.return_value = created_lead

        res = self.client.post(
            "/api/v1/leads",
            headers=self.auth_headers,
            json={
                "full_name": "QA SCRUM 126",
                "phone": "0912612626",
                "email": "qa.s126@example.com",
                "source": "direct",
                "interested_program_id": prog_id,
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "Tạo khách hàng tiềm năng thành công.")
        self.assertFalse(data["duplicate_warning"])
        self.assertEqual(data["data"]["full_name"], "QA SCRUM 126")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_create_lead_name_required(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.post(
            "/api/v1/leads",
            headers=self.auth_headers,
            json={"full_name": "", "phone": "0912612626"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "NAME_REQUIRED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_03_create_lead_phone_required(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.post(
            "/api/v1/leads",
            headers=self.auth_headers,
            json={"full_name": "QA User", "phone": "   "},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PHONE_REQUIRED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.lead_repository.get_lead_by_phone")
    @patch("app.repositories.lead_repository.insert_lead")
    def test_04_create_lead_duplicate_phone_warns(
        self, mock_insert, mock_get_phone, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        existing_lead = Lead(
            id=str(uuid.uuid4()),
            full_name="Nguyễn Văn A",
            phone="0912345678",
            source=LEAD_SOURCE_PUBLIC_FORM,
        )
        mock_get_phone.return_value = existing_lead

        new_lead = Lead(
            id=str(uuid.uuid4()),
            full_name="Nguyễn Văn B",
            phone="0912345678",
            source=LEAD_SOURCE_DIRECT,
        )
        mock_insert.return_value = new_lead

        res = self.client.post(
            "/api/v1/leads",
            headers=self.auth_headers,
            json={"full_name": "Nguyễn Văn B", "phone": "0912345678"},
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["duplicate_warning"])
        self.assertEqual(data["existing_lead"]["full_name"], "Nguyễn Văn A")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.lead_repository.get_lead_by_phone")
    def test_05_check_phone_endpoint(
        self, mock_get_phone, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        mock_get_phone.return_value = Lead(
            id="lead-1",
            full_name="Nguyễn Văn A",
            phone="0912345678",
        )

        res = self.client.get(
            "/api/v1/leads/check-phone?phone=0912345678",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertTrue(data["exists"])
        self.assertEqual(data["lead"]["full_name"], "Nguyễn Văn A")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.lead_repository.get_lead_by_id")
    @patch("app.repositories.lead_repository.get_lead_by_phone")
    @patch("app.repositories.lead_repository.update_lead_info")
    def test_06_update_lead_info_success(
        self, mock_update, mock_get_phone, mock_get_id, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lead_id = str(uuid.uuid4())
        lead = Lead(
            id=lead_id,
            full_name="Tên Cũ",
            phone="0911111111",
            source=LEAD_SOURCE_DIRECT,
        )
        mock_get_id.return_value = lead
        mock_get_phone.return_value = None

        updated_lead = Lead(
            id=lead_id,
            full_name="Tên Mới",
            phone="0922222222",
            source=LEAD_SOURCE_DIRECT,
        )
        mock_update.return_value = updated_lead

        res = self.client.put(
            f"/api/v1/leads/{lead_id}",
            headers=self.auth_headers,
            json={
                "full_name": "Tên Mới",
                "phone": "0922222222",
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "Cập nhật khách hàng tiềm năng thành công.")
        self.assertEqual(data["data"]["full_name"], "Tên Mới")


if __name__ == "__main__":
    unittest.main()
