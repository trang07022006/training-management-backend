"""
Bộ kiểm thử tích hợp & đơn vị cho SCRUM-215: LEAD TO STUDENT (Sub-task 215-01).
Kiểm tra API POST /api/v1/leads/<id>/convert-to-student.
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.config.jwt_handlers import register_jwt_handlers
from app.database.connection import get_db_connection
from app.database.ensure_business_roles import ensure_business_roles
from app.models.lead import (
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_STATUS_NEW,
    LEAD_STATUS_WON,
    Lead,
)
from app.models.login_session import LoginSession
from app.repositories import lead_repository, student_repository
from app.routes.lead_routes import lead_bp


class Scrum215LeadToStudentApiTests(unittest.TestCase):
    """Bộ kiểm thử cho SCRUM-215: Chuyển dữ liệu Lead sang hồ sơ học viên."""

    @classmethod
    def setUpClass(cls):
        ensure_business_roles()

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum215-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(lead_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        self.admin_user_id = "34068d8d-b2ec-4ce4-977a-28ac1b9b70de"
        self.authorized_session = LoginSession(
            session_id="session-authorized-215",
            user_id=self.admin_user_id,
            refresh_jti="ref-auth-215",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(hours=8),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.access_token = create_access_token(
                identity=self.admin_user_id,
                additional_claims={"sid": self.authorized_session.session_id},
            )
        self.auth_headers = {"Authorization": f"Bearer {self.access_token}"}

        # Lưu lại danh sách ID cần dọn dẹp sau test
        self.created_lead_ids: list[str] = []
        self.created_student_ids: list[str] = []

    def tearDown(self):
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                for student_id in self.created_student_ids:
                    cursor.execute("DELETE FROM students WHERE id = %s", (student_id,))
                for lead_id in self.created_lead_ids:
                    cursor.execute("DELETE FROM students WHERE lead_id = %s", (lead_id,))
                    cursor.execute("DELETE FROM leads WHERE id = %s", (lead_id,))
            conn.commit()
        finally:
            conn.close()

    def _create_test_lead(self, status: str = LEAD_STATUS_WON) -> Lead:
        lead_id = str(uuid.uuid4())
        lead = Lead(
            id=lead_id,
            full_name="Nguyễn Văn Chốt Học",
            phone="0988776655",
            email=f"chot.{uuid.uuid4().hex[:6]}@example.com",
            interested_program_id=None,
            message="Đã đồng ý nhập học khóa Lập trình",
            source=LEAD_SOURCE_PUBLIC_FORM,
            status=status,
            created_at=self.now,
            updated_at=self.now,
        )
        created = lead_repository.insert_lead(lead)
        self.created_lead_ids.append(created.id)
        return created

    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc215_01_convert_won_lead_success(self, mock_get_session):
        """TC215-01: Chuyển Lead đã chốt thành hồ sơ học viên thành công."""
        mock_get_session.return_value = self.authorized_session
        lead = self._create_test_lead(status=LEAD_STATUS_WON)

        response = self.client.post(
            f"/api/v1/leads/{lead.id}/convert-to-student",
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data["code"], "CONVERT_SUCCESS")
        self.assertIn("data", data)
        student_data = data["data"]["student"]
        self.created_student_ids.append(student_data["id"])

        self.assertEqual(student_data["lead_id"], lead.id)
        self.assertEqual(student_data["full_name"], lead.full_name)
        self.assertEqual(student_data["phone"], lead.phone)
        self.assertEqual(student_data["email"], lead.email)
        self.assertIsNotNone(student_data["student_code"])

        # Kiểm tra trong DB thật
        persisted = student_repository.get_student_by_id(student_data["id"])
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.lead_id, lead.id)
        self.assertEqual(persisted.full_name, lead.full_name)

    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc215_02_student_data_reused_from_lead(self, mock_get_session):
        """TC215-02: Dữ liệu Lead có sẵn được chuyển sang, không bắt user nhập lại."""
        mock_get_session.return_value = self.authorized_session
        lead = self._create_test_lead(status=LEAD_STATUS_WON)

        response = self.client.post(
            f"/api/v1/leads/{lead.id}/convert-to-student",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 201)
        student_data = response.get_json()["data"]["student"]
        self.created_student_ids.append(student_data["id"])

        # Kiểm tra reuse chính xác các trường
        self.assertEqual(student_data["full_name"], lead.full_name)
        self.assertEqual(student_data["phone"], lead.phone)
        self.assertEqual(student_data["email"], lead.email)

    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc215_03_non_won_lead_cannot_be_converted(self, mock_get_session):
        """TC215-03: Lead chưa Chốt (ví dụ new) không thể chuyển đổi thành học viên."""
        mock_get_session.return_value = self.authorized_session
        lead = self._create_test_lead(status=LEAD_STATUS_NEW)

        response = self.client.post(
            f"/api/v1/leads/{lead.id}/convert-to-student",
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["code"], "LEAD_NOT_WON")
        self.assertIn("Chỉ có thể chuyển đổi Lead có trạng thái Chốt", data["message"])

        # Không tạo record trong students
        student = student_repository.get_student_by_lead_id(lead.id)
        self.assertIsNone(student)

    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc215_04_duplicate_conversion_prevented(self, mock_get_session):
        """TC215-04: Ngăn chặn chuyển đổi trùng lặp cùng một Lead."""
        mock_get_session.return_value = self.authorized_session
        lead = self._create_test_lead(status=LEAD_STATUS_WON)

        # Lần 1: Thành công
        res1 = self.client.post(
            f"/api/v1/leads/{lead.id}/convert-to-student",
            headers=self.auth_headers,
        )
        self.assertEqual(res1.status_code, 201)
        self.created_student_ids.append(res1.get_json()["data"]["student"]["id"])

        # Lần 2: Thử convert lại -> Bị chặn
        res2 = self.client.post(
            f"/api/v1/leads/{lead.id}/convert-to-student",
            headers=self.auth_headers,
        )
        self.assertEqual(res2.status_code, 400)
        data2 = res2.get_json()
        self.assertEqual(data2["code"], "LEAD_ALREADY_CONVERTED")
        self.assertIn("đã được chuyển thành hồ sơ học viên trước đó", data2["message"])

    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc215_05_convert_nonexistent_lead_returns_404(self, mock_get_session):
        """TC215-05: Chuyển đổi Lead không tồn tại trả về lỗi 404."""
        mock_get_session.return_value = self.authorized_session
        random_id = str(uuid.uuid4())

        response = self.client.post(
            f"/api/v1/leads/{random_id}/convert-to-student",
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertEqual(data["code"], "LEAD_NOT_FOUND")
