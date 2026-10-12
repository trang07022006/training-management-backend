"""
Test suite cho SCRUM-217: Mở lớp từ chương trình đào tạo (TC217-01 -> TC217-10).
- Sub-task 217-01: Khai báo thông tin lớp (mã lớp, chương trình, ngày khai giảng dự kiến, sĩ số tối đa, hình thức học).
- Sub-task 217-02: Mã lớp là duy nhất (enforce UNIQUE, chặn duplicate).
- Sub-task 217-03: Vòng đời lớp (Chuẩn bị -> Đang học -> Kết thúc -> Huỷ).
- Sub-task 217-04: Sao chép danh sách môn học từ chương trình khi mở lớp.
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid
from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.database.ensure_business_roles import ensure_business_roles
from app.main import app
from app.models.login_session import LoginSession
from app.models.training_program import TrainingProgram
from app.models.subject import Subject
from app.repositories import (
    class_repository,
    program_subject_repository,
    subject_repository,
    training_program_repository,
)


class Scrum217ClassCreationApiTests(unittest.TestCase):
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
            refresh_jti="ref-auth-217",
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
        self.cleanup_program_ids = []
        self.cleanup_subject_ids = []

    def tearDown(self):
        for cid in self.cleanup_class_ids:
            try:
                class_repository.delete_class_for_testing(cid)
            except Exception:
                pass

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                for pid in self.cleanup_program_ids:
                    cursor.execute("DELETE FROM program_subjects WHERE program_id = %s", (pid,))
                    cursor.execute("DELETE FROM training_programs WHERE id = %s", (pid,))
                for sid in self.cleanup_subject_ids:
                    cursor.execute("DELETE FROM subjects WHERE id = %s", (sid,))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def _create_test_program(self, code_suffix: str = "") -> TrainingProgram:
        """Tạo một chương trình đào tạo test."""
        prog_id = str(uuid.uuid4())
        prog_code = f"PROG-217-{uuid.uuid4().hex[:6].upper()}{code_suffix}"
        prog = TrainingProgram(
            id=prog_id,
            code=prog_code,
            name=f"Chương trình Đào tạo Test {prog_code}",
            description="Mô tả test",
            duration_semesters=8,
            standard_tuition_fee=15000000,
            status="active",
            created_at=self.now,
            updated_at=self.now,
        )
        created = training_program_repository.insert_training_program(prog)
        self.cleanup_program_ids.append(created.id)
        return created

    def _create_test_subject(self, code_suffix: str = "") -> Subject:
        """Tạo một môn học test."""
        subj_id = str(uuid.uuid4())
        subj_code = f"SUBJ-{uuid.uuid4().hex[:6].upper()}{code_suffix}"
        subj = Subject(
            id=subj_id,
            code=subj_code,
            name=f"Môn học Test {subj_code}",
            description="Mô tả môn học test",
            credits=3,
            total_sessions=45,
            status="active",
            created_at=self.now,
            updated_at=self.now,
        )
        created = subject_repository.insert_subject(subj)
        self.cleanup_subject_ids.append(created.id)
        return created

    # =========================================================================
    # 217-01: KHAI BÁO THÔNG TIN LỚP
    # =========================================================================

    def test_tc217_01_create_class_success(self):
        """TC217-01: Tạo lớp hợp lệ -> tạo thành công (201)."""
        program = self._create_test_program()
        class_code = f"CLASS-{uuid.uuid4().hex[:6].upper()}"

        payload = {
            "class_code": class_code,
            "program_id": program.id,
            "expected_start_date": "2026-05-15",
            "max_capacity": 35,
            "learning_mode": "offline",
        }

        resp = self.client.post("/api/v1/classes", json=payload, headers=self.headers)
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["data"]
        self.cleanup_class_ids.append(data["id"])

        self.assertEqual(data["class_code"], class_code)
        self.assertEqual(data["program_id"], program.id)
        self.assertEqual(data["expected_start_date"], "2026-05-15")
        self.assertEqual(data["max_capacity"], 35)
        self.assertEqual(data["learning_mode"], "offline")
        self.assertEqual(data["status"], "preparing")
        self.assertEqual(data["status_label"], "Chuẩn bị")

    def test_tc217_02_query_class_persists_in_database(self):
        """TC217-02: Reload/query lại -> dữ liệu lớp vẫn tồn tại trong DB."""
        program = self._create_test_program()
        class_code = f"CLASS-{uuid.uuid4().hex[:6].upper()}"

        payload = {
            "class_code": class_code,
            "program_id": program.id,
            "expected_start_date": "2026-06-01",
            "max_capacity": 40,
            "learning_mode": "online",
        }
        create_resp = self.client.post("/api/v1/classes", json=payload, headers=self.headers)
        class_id = create_resp.get_json()["data"]["id"]
        self.cleanup_class_ids.append(class_id)

        # GET lại từ API
        get_resp = self.client.get(f"/api/v1/classes/{class_id}", headers=self.headers)
        self.assertEqual(get_resp.status_code, 200)
        persisted = get_resp.get_json()["data"]
        self.assertEqual(persisted["id"], class_id)
        self.assertEqual(persisted["class_code"], class_code)
        self.assertEqual(persisted["learning_mode"], "online")
        self.assertEqual(persisted["max_capacity"], 40)

        # Kiểm tra trực tiếp qua repository
        direct = class_repository.get_class_by_id(class_id)
        self.assertIsNotNone(direct)
        self.assertEqual(direct.class_code, class_code)

    # =========================================================================
    # 217-02: MÃ LỚP DUY NHẤT
    # =========================================================================

    def test_tc217_03_and_04_unique_class_code_enforced(self):
        """TC217-03 & 04: Tạo CLASS001 thành công, tạo lớp thứ 2 trùng mã bị chặn."""
        program = self._create_test_program()
        duplicate_code = f"CLASS-UNIQUE-{uuid.uuid4().hex[:6].upper()}"

        # Lần 1: Tạo lớp đầu tiên -> PASS (TC217-03)
        payload1 = {
            "class_code": duplicate_code,
            "program_id": program.id,
            "max_capacity": 30,
        }
        resp1 = self.client.post("/api/v1/classes", json=payload1, headers=self.headers)
        self.assertEqual(resp1.status_code, 201)
        self.cleanup_class_ids.append(resp1.get_json()["data"]["id"])

        # Lần 2: Tạo lớp khác trùng mã -> Bị chặn (TC217-04)
        payload2 = {
            "class_code": duplicate_code,
            "program_id": program.id,
            "max_capacity": 25,
        }
        resp2 = self.client.post("/api/v1/classes", json=payload2, headers=self.headers)
        self.assertIn(resp2.status_code, (409, 400))
        body2 = resp2.get_json()
        self.assertEqual(body2["code"], "CLASS_CODE_ALREADY_EXISTS")
        self.assertIn("đã tồn tại", body2["message"])

    # =========================================================================
    # 217-03: VÒNG ĐỜI LỚP
    # =========================================================================

    def test_tc217_05_class_default_status_valid(self):
        """TC217-05: Class khi khởi tạo có status 'preparing' (Chuẩn bị)."""
        program = self._create_test_program()
        code = f"CLASS-{uuid.uuid4().hex[:6].upper()}"
        resp = self.client.post("/api/v1/classes", json={"class_code": code, "program_id": program.id}, headers=self.headers)
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["data"]
        self.cleanup_class_ids.append(data["id"])
        self.assertEqual(data["status"], "preparing")
        self.assertEqual(data["status_label"], "Chuẩn bị")

    def test_tc217_06_lifecycle_four_states_transitions(self):
        """TC217-06: Vòng đời hỗ trợ đúng 4 trạng thái: Chuẩn bị -> Đang học -> Kết thúc -> Huỷ."""
        program = self._create_test_program()
        code = f"CLASS-{uuid.uuid4().hex[:6].upper()}"
        resp = self.client.post("/api/v1/classes", json={"class_code": code, "program_id": program.id}, headers=self.headers)
        class_id = resp.get_json()["data"]["id"]
        self.cleanup_class_ids.append(class_id)

        # 1. Chuyển sang Đang học
        resp_learn = self.client.put(f"/api/v1/classes/{class_id}/status", json={"status": "in_progress"}, headers=self.headers)
        self.assertEqual(resp_learn.status_code, 200)
        self.assertEqual(resp_learn.get_json()["data"]["status"], "in_progress")
        self.assertEqual(resp_learn.get_json()["data"]["status_label"], "Đang học")

        # 2. Chuyển sang Kết thúc
        resp_done = self.client.put(f"/api/v1/classes/{class_id}/status", json={"status": "completed"}, headers=self.headers)
        self.assertEqual(resp_done.status_code, 200)
        self.assertEqual(resp_done.get_json()["data"]["status"], "completed")
        self.assertEqual(resp_done.get_json()["data"]["status_label"], "Kết thúc")

        # 3. Chuyển sang Huỷ (có thể nhận tiếng Việt 'Huỷ' hoặc 'cancelled')
        resp_cancel = self.client.put(f"/api/v1/classes/{class_id}/status", json={"status": "cancelled"}, headers=self.headers)
        self.assertEqual(resp_cancel.status_code, 200)
        self.assertEqual(resp_cancel.get_json()["data"]["status"], "cancelled")
        self.assertEqual(resp_cancel.get_json()["data"]["status_label"], "Huỷ")

        # 4. Trạng thái không hợp lệ ngoài 4 trạng thái trên -> Bị chặn
        resp_invalid = self.client.put(f"/api/v1/classes/{class_id}/status", json={"status": "random_invalid_status"}, headers=self.headers)
        self.assertEqual(resp_invalid.status_code, 400)
        self.assertEqual(resp_invalid.get_json()["code"], "INVALID_CLASS_STATUS")

    def test_tc217_07_lifecycle_status_persists(self):
        """TC217-07: Reload -> status persist trong database."""
        program = self._create_test_program()
        code = f"CLASS-{uuid.uuid4().hex[:6].upper()}"
        resp = self.client.post("/api/v1/classes", json={"class_code": code, "program_id": program.id}, headers=self.headers)
        class_id = resp.get_json()["data"]["id"]
        self.cleanup_class_ids.append(class_id)

        self.client.put(f"/api/v1/classes/{class_id}/status", json={"status": "in_progress"}, headers=self.headers)

        # GET lại
        get_resp = self.client.get(f"/api/v1/classes/{class_id}", headers=self.headers)
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.get_json()["data"]["status"], "in_progress")

    # =========================================================================
    # 217-04: SAO CHÉP DANH SÁCH MÔN HỌC
    # =========================================================================

    def test_tc217_08_copy_program_subjects_to_class(self):
        """TC217-08: Program có môn học -> Class mới có danh sách tương ứng."""
        program = self._create_test_program()
        subject1 = self._create_test_subject("1")
        subject2 = self._create_test_subject("2")

        # Gán 2 môn học vào chương trình đào tạo
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO program_subjects (id, program_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at)
                    VALUES (%s, %s, %s, 1, 1, 1, %s, %s),
                           (%s, %s, %s, 1, 0, 2, %s, %s)
                    """,
                    (
                        str(uuid.uuid4()), program.id, subject1.id, self.now, self.now,
                        str(uuid.uuid4()), program.id, subject2.id, self.now, self.now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

        # Tạo lớp từ chương trình
        code = f"CLASS-COPY-{uuid.uuid4().hex[:6].upper()}"
        resp = self.client.post(
            "/api/v1/classes",
            json={"class_code": code, "program_id": program.id, "max_capacity": 30},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["data"]
        class_id = data["id"]
        self.cleanup_class_ids.append(class_id)

        # Kiểm tra danh sách môn học đã sao chép trả về
        subjects = data["subjects"]
        self.assertEqual(len(subjects), 2)
        copied_subject_ids = [s["subject_id"] for s in subjects]
        self.assertIn(subject1.id, copied_subject_ids)
        self.assertIn(subject2.id, copied_subject_ids)

    def test_tc217_09_original_program_subjects_remain_unchanged(self):
        """TC217-09: Kiểm tra Program gốc không bị thay đổi sau khi sao chép sang lớp."""
        program = self._create_test_program()
        subject = self._create_test_subject()

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO program_subjects (id, program_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at)
                    VALUES (%s, %s, %s, 1, 1, 1, %s, %s)
                    """,
                    (str(uuid.uuid4()), program.id, subject.id, self.now, self.now),
                )
            conn.commit()
        finally:
            conn.close()

        # Mở lớp
        code = f"CLASS-IMMUTABLE-{uuid.uuid4().hex[:6].upper()}"
        resp = self.client.post(
            "/api/v1/classes",
            json={"class_code": code, "program_id": program.id},
            headers=self.headers,
        )
        self.cleanup_class_ids.append(resp.get_json()["data"]["id"])

        # Kiểm tra lại program_subjects của program gốc
        conn = get_db_connection()
        try:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute("SELECT * FROM program_subjects WHERE program_id = %s", (program.id,))
                rows = cursor.fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["subject_id"], subject.id)
        finally:
            conn.close()

    def test_tc217_10_reload_class_subjects_persists(self):
        """TC217-10: Reload / GET /api/v1/classes/<id>/subjects -> subject list persist."""
        program = self._create_test_program()
        subject = self._create_test_subject()

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO program_subjects (id, program_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at)
                    VALUES (%s, %s, %s, 2, 1, 1, %s, %s)
                    """,
                    (str(uuid.uuid4()), program.id, subject.id, self.now, self.now),
                )
            conn.commit()
        finally:
            conn.close()

        code = f"CLASS-RELOAD-{uuid.uuid4().hex[:6].upper()}"
        resp = self.client.post(
            "/api/v1/classes",
            json={"class_code": code, "program_id": program.id},
            headers=self.headers,
        )
        class_id = resp.get_json()["data"]["id"]
        self.cleanup_class_ids.append(class_id)

        # GET /api/v1/classes/<class_id>/subjects
        subj_resp = self.client.get(f"/api/v1/classes/{class_id}/subjects", headers=self.headers)
        self.assertEqual(subj_resp.status_code, 200)
        items = subj_resp.get_json()["data"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["subject_id"], subject.id)
        self.assertEqual(items[0]["subject_code"], subject.code)
