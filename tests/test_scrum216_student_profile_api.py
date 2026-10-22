"""
Test suite cho SCRUM-216: Quản lý hồ sơ học viên (TC216-01 -> TC216-12).
- Sub-task 216-01: Xem và sửa hồ sơ học viên (thông tin cá nhân, trình độ đầu vào, ghi chú).
- Sub-task 216-02: Lớp đang học và lịch sử các lớp đã học.
- Sub-task 216-03: Tìm kiếm học viên theo mã học viên, tên, số điện thoại.
"""

from datetime import datetime, timezone
import unittest
import uuid

from app.database.connection import get_db_connection
from app.main import app
from app.models.student import Student
from app.repositories import student_repository
from flask_jwt_extended import create_access_token


from unittest.mock import patch
from datetime import timedelta
from app.models.login_session import LoginSession

class Scrum216StudentProfileApiTests(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.cleanup_student_ids = []
        self.admin_user_id = "34068d8d-b2ec-4ce4-977a-28ac1b9b70de"
        self.now = datetime.now(timezone.utc)
        self.session_id = f"test-session-{uuid.uuid4()}"
        self.authorized_session = LoginSession(
            session_id=self.session_id,
            user_id=self.admin_user_id,
            refresh_jti="ref-auth-216",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(hours=8),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.session_patcher = patch("app.utils.rbac_auth.get_session_by_id", return_value=self.authorized_session)
        self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)

        with self.app.app_context():
            self.token = create_access_token(
                identity=self.admin_user_id,
                additional_claims={
                    "roles": ["admin", "training_manager"],
                    "sid": self.session_id,
                },
            )
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def tearDown(self):
        if not self.cleanup_student_ids:
            return
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                for sid in self.cleanup_student_ids:
                    cursor.execute("DELETE FROM students WHERE id = %s", (sid,))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def _create_test_student(
        self,
        full_name: str = "Nguyễn Văn Test 216",
        phone: str = "0987654321",
        email: str = "test216@ictu.edu.vn",
        entry_level: str | None = "IELTS 5.5",
        notes: str | None = "Ghi chú ban đầu",
    ) -> Student:
        student_id = str(uuid.uuid4())
        student_code = student_repository.generate_next_student_code()
        student = Student(
            id=student_id,
            student_code=student_code,
            full_name=full_name,
            phone=phone,
            email=email,
            status="enrolled",
            entry_level=entry_level,
            notes=notes,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        created = student_repository.create_student(student)
        self.cleanup_student_ids.append(created.id)
        return created

    # =========================================================================
    # 216-01: XEM VÀ SỬA HỒ SƠ HỌC VIÊN
    # =========================================================================

    def test_tc216_01_view_student_profile(self):
        """TC216-01: Mở Student tạo từ SCRUM-215 -> hồ sơ hiển thị đúng."""
        student = self._create_test_student()
        resp = self.client.get(f"/api/v1/students/{student.id}", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()["data"]
        self.assertEqual(data["id"], student.id)
        self.assertEqual(data["student_code"], student.student_code)
        self.assertEqual(data["full_name"], student.full_name)
        self.assertEqual(data["phone"], student.phone)
        self.assertEqual(data["email"], student.email)
        self.assertEqual(data["entry_level"], student.entry_level)
        self.assertEqual(data["notes"], student.notes)

    def test_tc216_02_update_personal_info(self):
        """TC216-02: Sửa thông tin cá nhân -> lưu thành công."""
        student = self._create_test_student()
        payload = {
            "full_name": "Nguyễn Văn Đã Sửa",
            "phone": "0912345678",
            "email": "updated_student@ictu.edu.vn",
        }
        resp = self.client.put(f"/api/v1/students/{student.id}", json=payload, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()["data"]
        self.assertEqual(data["full_name"], "Nguyễn Văn Đã Sửa")
        self.assertEqual(data["phone"], "0912345678")
        self.assertEqual(data["email"], "updated_student@ictu.edu.vn")
        # student_code không thay đổi
        self.assertEqual(data["student_code"], student.student_code)

    def test_tc216_03_update_entry_level(self):
        """TC216-03: Sửa trình độ đầu vào -> lưu thành công."""
        student = self._create_test_student()
        payload = {"entry_level": "TOEIC 750 (Đầu vào B2)"}
        resp = self.client.put(f"/api/v1/students/{student.id}", json=payload, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()["data"]
        self.assertEqual(data["entry_level"], "TOEIC 750 (Đầu vào B2)")

    def test_tc216_04_update_notes(self):
        """TC216-04: Sửa ghi chú -> lưu thành công."""
        student = self._create_test_student()
        payload = {"notes": "Đã hoàn thành thủ tục đăng ký bổ sung."}
        resp = self.client.put(f"/api/v1/students/{student.id}", json=payload, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()["data"]
        self.assertEqual(data["notes"], "Đã hoàn thành thủ tục đăng ký bổ sung.")

    def test_tc216_05_reload_data_persists(self):
        """TC216-05: Reload / query lại -> dữ liệu sửa đổi vẫn tồn tại trong database."""
        student = self._create_test_student()
        payload = {
            "full_name": "Trần Thị Persistent",
            "entry_level": "B1 Cao cấp",
            "notes": "Kiểm tra lưu DB thật",
        }
        self.client.put(f"/api/v1/students/{student.id}", json=payload, headers=self.headers)

        # GET lại từ API
        get_resp = self.client.get(f"/api/v1/students/{student.id}", headers=self.headers)
        self.assertEqual(get_resp.status_code, 200)
        persisted = get_resp.get_json()["data"]
        self.assertEqual(persisted["full_name"], "Trần Thị Persistent")
        self.assertEqual(persisted["entry_level"], "B1 Cao cấp")
        self.assertEqual(persisted["notes"], "Kiểm tra lưu DB thật")

    # =========================================================================
    # 216-02: LỚP ĐANG HỌC VÀ LỊCH SỬ LỚP
    # =========================================================================

    def test_tc216_06_student_without_classes_returns_empty_state(self):
        """TC216-06: Student chưa có lớp -> current_class là None, class_history là []."""
        student = self._create_test_student()
        resp = self.client.get(f"/api/v1/students/{student.id}", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()["data"]
        self.assertIsNone(data["current_class"])
        self.assertEqual(data["class_history"], [])

    def test_tc216_07_and_08_classes_relation_structure(self):
        """TC216-07 & 08: Cấu trúc response sẵn sàng cho SCRUM-218 đưa quan hệ lớp vào."""
        student = self._create_test_student()
        resp = self.client.get(f"/api/v1/students/{student.id}", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()["data"]
        self.assertIn("current_class", data)
        self.assertIn("class_history", data)

    # =========================================================================
    # 216-03: TÌM KIẾM HỌC VIÊN
    # =========================================================================

    def test_tc216_09_search_by_student_code(self):
        """TC216-09: Search theo student_code -> đúng Student."""
        student = self._create_test_student(full_name="Tìm Kiếm Theo Mã", phone="0911223344")
        resp = self.client.get(f"/api/v1/students?search={student.student_code}", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        items = resp.get_json()["data"]["items"]
        self.assertTrue(any(item["id"] == student.id for item in items))
        self.assertEqual(items[0]["student_code"], student.student_code)

    def test_tc216_10_search_by_name(self):
        """TC216-10: Search theo tên -> đúng Student phù hợp."""
        unique_name = f"Học Viên Tìm Kiếm {uuid.uuid4().hex[:6]}"
        student = self._create_test_student(full_name=unique_name)
        resp = self.client.get(f"/api/v1/students?search={unique_name}", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        items = resp.get_json()["data"]["items"]
        self.assertTrue(any(item["id"] == student.id for item in items))

    def test_tc216_11_search_by_phone(self):
        """TC216-11: Search theo số điện thoại -> đúng Student phù hợp."""
        unique_phone = f"099{uuid.uuid4().hex[:7]}"
        student = self._create_test_student(phone=unique_phone)
        resp = self.client.get(f"/api/v1/students?search={unique_phone}", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        items = resp.get_json()["data"]["items"]
        self.assertTrue(any(item["id"] == student.id for item in items))

    def test_tc216_12_search_no_results(self):
        """TC216-12: Search không có kết quả -> empty state đúng, không lỗi."""
        resp = self.client.get("/api/v1/students?search=NON_EXISTENT_STUDENT_CODE_99999", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()["data"]
        self.assertEqual(data["items"], [])
        self.assertEqual(data["total"], 0)
