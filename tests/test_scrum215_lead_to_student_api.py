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
    def test_tc215_nonexistent_lead_returns_404(self, mock_get_session):
        """TC215-404: Chuyển đổi Lead không tồn tại trả về lỗi 404."""
        mock_get_session.return_value = self.authorized_session
        random_id = str(uuid.uuid4())

        response = self.client.post(
            f"/api/v1/leads/{random_id}/convert-to-student",
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertEqual(data["code"], "LEAD_NOT_FOUND")

    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc215_05_convert_won_lead_generates_student_code_automatically(self, mock_get_session):
        """TC215-05: Convert một Lead đã Chốt -> Student được tạo với student_code tự động."""
        mock_get_session.return_value = self.authorized_session
        lead = self._create_test_lead(status=LEAD_STATUS_WON)

        response = self.client.post(
            f"/api/v1/leads/{lead.id}/convert-to-student",
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        student_data = data["data"]["student"]
        self.created_student_ids.append(student_data["id"])

        student_code = student_data.get("student_code")
        self.assertIsNotNone(student_code)
        self.assertTrue(len(student_code) > 0)
        self.assertTrue(
            student_code.startswith("STU"),
            f"Expected code to start with STU, got {student_code}",
        )
        self.assertEqual(len(student_code), 9)  # STU + 6 digits = 9 chars

    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc215_06_convert_second_lead_generates_different_code(self, mock_get_session):
        """TC215-06: Convert Lead thứ hai -> student_code khác Student thứ nhất."""
        mock_get_session.return_value = self.authorized_session
        lead1 = self._create_test_lead(status=LEAD_STATUS_WON)
        lead2 = self._create_test_lead(status=LEAD_STATUS_WON)

        res1 = self.client.post(
            f"/api/v1/leads/{lead1.id}/convert-to-student",
            headers=self.auth_headers,
        )
        self.assertEqual(res1.status_code, 201)
        code1 = res1.get_json()["data"]["student"]["student_code"]
        self.created_student_ids.append(res1.get_json()["data"]["student"]["id"])

        res2 = self.client.post(
            f"/api/v1/leads/{lead2.id}/convert-to-student",
            headers=self.auth_headers,
        )
        self.assertEqual(res2.status_code, 201)
        code2 = res2.get_json()["data"]["student"]["student_code"]
        self.created_student_ids.append(res2.get_json()["data"]["student"]["id"])

        self.assertNotEqual(code1, code2, "Hai học viên chuyển đổi liên tiếp không được trùng mã!")

    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc215_07_request_without_student_code_still_auto_generates(self, mock_get_session):
        """TC215-07: Không nhập student_code từ UI/request -> backend vẫn tự sinh student_code."""
        mock_get_session.return_value = self.authorized_session
        lead = self._create_test_lead(status=LEAD_STATUS_WON)

        # Gửi request không có body hoặc cố ý gửi custom code giả định
        response = self.client.post(
            f"/api/v1/leads/{lead.id}/convert-to-student",
            headers=self.auth_headers,
            json={"student_code": "FORCED_MANUAL_CODE_NOT_ALLOWED"},
        )

        self.assertEqual(response.status_code, 201)
        student_data = response.get_json()["data"]["student"]
        self.created_student_ids.append(student_data["id"])

        # Mã sinh ra phải do hệ thống tự sinh theo prefix STU, không dùng custom code từ client
        self.assertNotEqual(student_data["student_code"], "FORCED_MANUAL_CODE_NOT_ALLOWED")
        self.assertTrue(student_data["student_code"].startswith("STU"))

    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc215_08_reload_query_student_preserves_student_code(self, mock_get_session):
        """TC215-08: Reload/query Student -> student_code vẫn tồn tại đúng trong DB."""
        mock_get_session.return_value = self.authorized_session
        lead = self._create_test_lead(status=LEAD_STATUS_WON)

        response = self.client.post(
            f"/api/v1/leads/{lead.id}/convert-to-student",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 201)
        student_data = response.get_json()["data"]["student"]
        self.created_student_ids.append(student_data["id"])
        original_code = student_data["student_code"]

        # Query lại bằng ID
        persisted_by_id = student_repository.get_student_by_id(student_data["id"])
        self.assertIsNotNone(persisted_by_id)
        self.assertEqual(persisted_by_id.student_code, original_code)

        # Query lại bằng mã học viên
        persisted_by_code = student_repository.get_student_by_code(original_code)
        self.assertIsNotNone(persisted_by_code)
        self.assertEqual(persisted_by_code.id, student_data["id"])

    def test_tc215_09_uniqueness_enforced_cannot_create_two_students_same_code(self):
        """TC215-09: Kiểm tra uniqueness -> không thể tạo hai Student có cùng student_code trong DB."""
        from app.models.student import Student

        unique_code = f"STU_TEST_{uuid.uuid4().hex[:6]}"
        s1 = Student(
            id=str(uuid.uuid4()),
            student_code=unique_code,
            full_name="Học Viên Duy Nhất 1",
            phone="0911000001",
            status="enrolled",
            created_at=self.now,
            updated_at=self.now,
        )
        student_repository.create_student(s1)
        self.created_student_ids.append(s1.id)

        # Thử tạo Student thứ 2 với cùng student_code
        s2 = Student(
            id=str(uuid.uuid4()),
            student_code=unique_code,
            full_name="Học Viên Trùng Mã 2",
            phone="0911000002",
            status="enrolled",
            created_at=self.now,
            updated_at=self.now,
        )
        with self.assertRaises(Exception):
            student_repository.create_student(s2)
