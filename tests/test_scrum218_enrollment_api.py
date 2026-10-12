"""
Test suite cho SCRUM-218: Ghi danh học viên vào lớp (TC218-01 -> TC218-12).
- Sub-task 218-01: Ghi danh đơn lẻ và hàng loạt (TC218-01, TC218-02, TC218-03).
- Sub-task 218-02: Chặn lớp đầy và ghi danh trùng (TC218-04, TC218-05, TC218-06, TC218-07).
- Sub-task 218-03: Ngày ghi danh và người thực hiện (TC218-08, TC218-09, TC218-10, TC218-11).
- Integration: Tích hợp ghi danh với hồ sơ học viên SCRUM-216 (TC218-12).
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid
from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.database.ensure_business_roles import ensure_business_roles
from app.main import app
from app.models.class_entity import ClassEntity
from app.models.login_session import LoginSession
from app.models.student import Student
from app.models.training_program import TrainingProgram
from app.repositories import (
    class_repository,
    enrollment_repository,
    student_repository,
    training_program_repository,
)


class Scrum218EnrollmentApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_business_roles()

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.admin_user_id = "34068d8d-b2ec-4ce4-977a-28ac1b9b70de"
        self.now = datetime.now(timezone.utc)
        self.session_id = f"test-session-{uuid.uuid4()}"
        self.authorized_session = LoginSession(
            session_id=self.session_id,
            user_id=self.admin_user_id,
            refresh_jti="ref-auth-218",
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

        self.cleanup_class_ids = []
        self.cleanup_student_ids = []
        self.cleanup_program_ids = []

    def tearDown(self):
        for cid in self.cleanup_class_ids:
            try:
                enrollment_repository.delete_enrollments_for_testing(cid)
                class_repository.delete_class_for_testing(cid)
            except Exception:
                pass

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                for sid in self.cleanup_student_ids:
                    cursor.execute("DELETE FROM class_enrollments WHERE student_id = %s", (sid,))
                    cursor.execute("DELETE FROM students WHERE id = %s", (sid,))
                for pid in self.cleanup_program_ids:
                    cursor.execute("DELETE FROM program_subjects WHERE program_id = %s", (pid,))
                    cursor.execute("DELETE FROM training_programs WHERE id = %s", (pid,))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def _create_test_program(self) -> TrainingProgram:
        prog_id = str(uuid.uuid4())
        prog_code = f"PROG-218-{uuid.uuid4().hex[:6].upper()}"
        prog = TrainingProgram(
            id=prog_id,
            code=prog_code,
            name=f"Chương trình Đào tạo Test {prog_code}",
            description="Mô tả test",
            status="active",
            standard_tuition_fee=5000000,
            duration_semesters=8,
            created_at=self.now,
            updated_at=self.now,
        )
        created = training_program_repository.insert_training_program(prog)
        self.cleanup_program_ids.append(created.id)
        return created

    def _create_test_class(self, program_id: str, max_capacity: int = 30) -> ClassEntity:
        class_id = str(uuid.uuid4())
        class_code = f"CLASS-218-{uuid.uuid4().hex[:6].upper()}"
        entity = ClassEntity(
            id=class_id,
            class_code=class_code,
            program_id=program_id,
            expected_start_date=self.now.date(),
            max_capacity=max_capacity,
            learning_mode="offline",
            status="preparing",
            created_at=self.now,
            updated_at=self.now,
        )
        created = class_repository.create_class(entity)
        self.cleanup_class_ids.append(created.id)
        return created

    def _create_test_student(self, name_suffix: str = "") -> Student:
        student_id = str(uuid.uuid4())
        student_code = f"HV218{uuid.uuid4().hex[:6].upper()}"
        student = Student(
            id=student_id,
            student_code=student_code,
            user_id=None,
            full_name=f"Học viên Test {name_suffix or student_code}",
            phone="0988776655",
            email=f"hv{uuid.uuid4().hex[:6]}@example.com",
            program_id=None,
            lead_id=None,
            status="enrolled",
            entry_level="Trung cấp",
            notes="Ghi chú test",
            created_at=self.now,
            updated_at=self.now,
        )
        created = student_repository.create_student(student)
        self.cleanup_student_ids.append(created.id)
        return created

    # =========================================================================
    # Sub-task 218-01: Ghi danh đơn lẻ và hàng loạt
    # =========================================================================

    def test_tc218_01_enroll_single_student_success(self):
        """TC218-01: Ghi danh 1 học viên đơn lẻ vào lớp học thành công (HTTP 201)."""
        prog = self._create_test_program()
        cls = self._create_test_class(prog.id, max_capacity=20)
        st = self._create_test_student("Đơn lẻ")

        payload = {"student_id": st.id}
        res = self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]
        self.assertEqual(data["class_id"], cls.id)
        self.assertEqual(data["enrolled_count"], 1)
        self.assertEqual(data["total_enrolled"], 1)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["student_id"], st.id)

    def test_tc218_02_enroll_bulk_students_success(self):
        """TC218-02: Ghi danh hàng loạt nhiều học viên vào lớp học thành công (HTTP 201)."""
        prog = self._create_test_program()
        cls = self._create_test_class(prog.id, max_capacity=20)
        st1 = self._create_test_student("Bulk 1")
        st2 = self._create_test_student("Bulk 2")
        st3 = self._create_test_student("Bulk 3")

        payload = {"student_ids": [st1.id, st2.id, st3.id]}
        res = self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]
        self.assertEqual(data["enrolled_count"], 3)
        self.assertEqual(data["total_enrolled"], 3)
        self.assertEqual(len(data["items"]), 3)

    def test_tc218_03_get_class_roster_returns_enrolled_students(self):
        """TC218-03: Xem danh sách học viên trong lớp (Roster) trả về đầy đủ học viên đã ghi danh (HTTP 200)."""
        prog = self._create_test_program()
        cls = self._create_test_class(prog.id, max_capacity=20)
        st1 = self._create_test_student("Roster 1")
        st2 = self._create_test_student("Roster 2")

        self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json={"student_ids": [st1.id, st2.id]})

        res = self.client.get(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["total"], 2)
        enrolled_student_ids = [item["student_id"] for item in data["items"]]
        self.assertIn(st1.id, enrolled_student_ids)
        self.assertIn(st2.id, enrolled_student_ids)
        self.assertEqual(data["class"]["class_code"], cls.class_code)

    # =========================================================================
    # Sub-task 218-02: Chặn lớp đầy và ghi danh trùng
    # =========================================================================

    def test_tc218_04_reject_when_class_capacity_full_single(self):
        """TC218-04: Chặn ghi danh đơn lẻ khi lớp đã đầy sĩ số tối đa (CLASS_CAPACITY_FULL)."""
        prog = self._create_test_program()
        # Lớp có sĩ số tối đa là 1
        cls = self._create_test_class(prog.id, max_capacity=1)
        st1 = self._create_test_student("1st")
        st2 = self._create_test_student("2nd")

        # Ghi danh học viên thứ nhất -> thành công
        res1 = self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json={"student_id": st1.id})
        self.assertEqual(res1.status_code, 201)

        # Ghi danh học viên thứ hai -> phải bị chặn do đầy lớp
        res2 = self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json={"student_id": st2.id})
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "CLASS_CAPACITY_FULL")
        self.assertIn("vượt quá", res2.get_json()["message"].lower())

    def test_tc218_05_reject_and_rollback_bulk_when_capacity_exceeded(self):
        """TC218-05: Chặn ghi danh hàng loạt khi tổng số lượng làm vượt quá sĩ số, rollback toàn bộ."""
        prog = self._create_test_program()
        # Lớp có sĩ số tối đa là 2
        cls = self._create_test_class(prog.id, max_capacity=2)
        st1 = self._create_test_student("Bulk Exceed 1")
        st2 = self._create_test_student("Bulk Exceed 2")
        st3 = self._create_test_student("Bulk Exceed 3")

        # Cố ghi danh cả 3 học viên vào lớp sĩ số 2
        res = self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json={"student_ids": [st1.id, st2.id, st3.id]})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "CLASS_CAPACITY_FULL")

        # Kiểm tra lớp vẫn trống (không ghi danh dở dang)
        roster_res = self.client.get(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers)
        self.assertEqual(roster_res.get_json()["data"]["total"], 0)

    def test_tc218_06_reject_duplicate_enrollment_single(self):
        """TC218-06: Chặn ghi danh khi học viên đã có trong lớp (STUDENT_ALREADY_ENROLLED)."""
        prog = self._create_test_program()
        cls = self._create_test_class(prog.id, max_capacity=20)
        st = self._create_test_student("Duplicate Single")

        # Ghi danh lần 1
        res1 = self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json={"student_id": st.id})
        self.assertEqual(res1.status_code, 201)

        # Ghi danh lần 2 học viên đó vào cùng lớp
        res2 = self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json={"student_id": st.id})
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "STUDENT_ALREADY_ENROLLED")
        self.assertIn("đã được ghi danh", res2.get_json()["message"])

    def test_tc218_07_reject_and_rollback_bulk_when_duplicate_present(self):
        """TC218-07: Chặn ghi danh hàng loạt nếu 1 học viên trong danh sách đã có trong lớp, rollback toàn bộ."""
        prog = self._create_test_program()
        cls = self._create_test_class(prog.id, max_capacity=20)
        st1 = self._create_test_student("Already In Class")
        st2 = self._create_test_student("New Student A")
        st3 = self._create_test_student("New Student B")

        # st1 đã có trong lớp từ trước
        self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json={"student_id": st1.id})

        # Ghi danh hàng loạt [st2, st1, st3] -> st1 bị trùng
        res = self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json={"student_ids": [st2.id, st1.id, st3.id]})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "STUDENT_ALREADY_ENROLLED")

        # Kiểm tra st2 và st3 không bị ghi danh dở dang (lớp chỉ có đúng st1)
        roster_res = self.client.get(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers)
        data = roster_res.get_json()["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["student_id"], st1.id)

    # =========================================================================
    # Sub-task 218-03: Ngày ghi danh và người thực hiện
    # =========================================================================

    def test_tc218_08_record_audit_enrolled_at_and_enrolled_by_from_jwt(self):
        """TC218-08: Ghi nhận đúng enrolled_at và enrolled_by lấy từ JWT actor identity."""
        prog = self._create_test_program()
        cls = self._create_test_class(prog.id, max_capacity=20)
        st = self._create_test_student("Audit Student")

        res = self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json={"student_id": st.id})
        self.assertEqual(res.status_code, 201)
        item = res.get_json()["data"]["items"][0]

        # enrolled_by phải là admin_user_id từ token JWT
        self.assertEqual(item["enrolled_by"], self.admin_user_id)
        # enrolled_at phải có giá trị ngày giờ
        self.assertIsNotNone(item["enrolled_at"])

    def test_tc218_09_roster_displays_enrolled_at_and_enrolled_by_details(self):
        """TC218-09: Roster view hiển thị đầy đủ thông tin enrolled_at và enrolled_by_name."""
        prog = self._create_test_program()
        cls = self._create_test_class(prog.id, max_capacity=20)
        st = self._create_test_student("Roster Detail")

        self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json={"student_id": st.id})

        res = self.client.get(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        roster_items = res.get_json()["data"]["items"]
        self.assertEqual(len(roster_items), 1)
        roster_item = roster_items[0]
        self.assertEqual(roster_item["student_id"], st.id)
        self.assertEqual(roster_item["student_code"], st.student_code)
        self.assertEqual(roster_item["full_name"], st.full_name)
        self.assertIsNotNone(roster_item["enrolled_at"])
        self.assertIsNotNone(roster_item["enrolled_by"])
        self.assertIsNotNone(roster_item["enrolled_by_name"])

    def test_tc218_10_reject_when_class_not_found(self):
        """TC218-10: Báo lỗi CLASS_NOT_FOUND (404) khi lớp học không tồn tại."""
        st = self._create_test_student("Nonexistent Class")
        fake_class_id = str(uuid.uuid4())
        res = self.client.post(f"/api/v1/classes/{fake_class_id}/enrollments", headers=self.headers, json={"student_id": st.id})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "CLASS_NOT_FOUND")

    def test_tc218_11_reject_when_student_not_found(self):
        """TC218-11: Báo lỗi STUDENT_NOT_FOUND (404) khi học viên không tồn tại."""
        prog = self._create_test_program()
        cls = self._create_test_class(prog.id, max_capacity=20)
        fake_student_id = str(uuid.uuid4())
        res = self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json={"student_id": fake_student_id})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "STUDENT_NOT_FOUND")

    # =========================================================================
    # Integration: SCRUM-218 ↔ SCRUM-216 Hồ sơ học viên
    # =========================================================================

    def test_tc218_12_student_profile_displays_enrolled_class_and_history(self):
        """TC218-12: Hồ sơ học viên (SCRUM-216 GET /api/v1/students/<id>) hiển thị lớp đang học."""
        prog = self._create_test_program()
        cls = self._create_test_class(prog.id, max_capacity=20)
        st = self._create_test_student("Integration Profile")

        # Ghi danh vào lớp
        self.client.post(f"/api/v1/classes/{cls.id}/enrollments", headers=self.headers, json={"student_id": st.id})

        # Gọi API chi tiết học viên SCRUM-216
        res = self.client.get(f"/api/v1/students/{st.id}", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        student_data = res.get_json()["data"]
        self.assertIsNotNone(student_data.get("current_class"))
        self.assertEqual(student_data["current_class"]["class_id"], cls.id)
        self.assertEqual(student_data["current_class"]["class_code"], cls.class_code)


if __name__ == "__main__":
    unittest.main()
