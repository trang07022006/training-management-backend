"""
Test suite cho SCRUM-219: Bộ lọc danh sách lớp học (TC219-01 -> TC219-06).
- TC219-01: Lọc trạng thái (preparing, in_progress, completed, cancelled)
- TC219-02: Lọc chương trình đào tạo
- TC219-03: Lọc giảng viên (dependency SCRUM-220: khi chưa có dữ liệu phân công thì không trả về sai)
- TC219-04: Lọc khoảng thời gian (theo expected_start_date)
- TC219-05: Kết hợp nhiều filter đồng thời
- TC219-06: Xóa/bỏ filter -> trả về danh sách đầy đủ
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid
from flask_jwt_extended import create_access_token

from app.database.ensure_business_roles import ensure_business_roles
from app.main import app
from app.models.login_session import LoginSession
from app.models.training_program import TrainingProgram
from app.repositories import class_repository, training_program_repository


class Scrum219ClassFiltersApiTests(unittest.TestCase):
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
            refresh_jti="ref-auth-219",
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

        # Tạo 2 training program test
        self.program_1 = training_program_repository.insert_training_program(
            TrainingProgram(
                id=str(uuid.uuid4()),
                code=f"PRG219A-{uuid.uuid4().hex[:6]}",
                name="CNTT Khóa 219A",
                duration_semesters=8,
                standard_tuition_fee=15000000,
                status="active",
                created_at=self.now,
                updated_at=self.now,
            )
        )
        self.program_2 = training_program_repository.insert_training_program(
            TrainingProgram(
                id=str(uuid.uuid4()),
                code=f"PRG219B-{uuid.uuid4().hex[:6]}",
                name="KTPM Khóa 219B",
                duration_semesters=8,
                standard_tuition_fee=16000000,
                status="active",
                created_at=self.now,
                updated_at=self.now,
            )
        )

        self.created_class_ids = []

    def tearDown(self):
        for cid in self.created_class_ids:
            try:
                class_repository.delete_class_for_testing(cid)
            except Exception:
                pass

        conn = class_repository.get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM classes WHERE program_id IN (%s, %s)", (self.program_1.id, self.program_2.id))
                cursor.execute("DELETE FROM training_programs WHERE id IN (%s, %s)", (self.program_1.id, self.program_2.id))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def _create_class(self, code_suffix, program_id, status="preparing", start_date="2026-06-01"):
        payload = {
            "class_code": f"CLS219-{code_suffix}-{uuid.uuid4().hex[:6]}",
            "program_id": program_id,
            "expected_start_date": start_date,
            "max_capacity": 30,
            "learning_mode": "offline",
            "status": status,
        }
        resp = self.client.post("/api/v1/classes", json=payload, headers=self.headers)
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["data"]
        self.created_class_ids.append(data["id"])
        return data

    def test_tc219_01_filter_status(self):
        """TC219-01: Lọc trạng thái chỉ hiển thị lớp có trạng thái tương ứng."""
        cls_prep = self._create_class("PREP", self.program_1.id, status="preparing")
        cls_prog = self._create_class("PROG", self.program_1.id, status="in_progress")

        resp = self.client.get("/api/v1/classes?status=preparing", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        items = resp.get_json()["data"]["items"]
        item_ids = [c["id"] for c in items]
        self.assertIn(cls_prep["id"], item_ids)
        self.assertNotIn(cls_prog["id"], item_ids)

        resp_prog = self.client.get("/api/v1/classes?status=in_progress", headers=self.headers)
        self.assertEqual(resp_prog.status_code, 200)
        prog_ids = [c["id"] for c in resp_prog.get_json()["data"]["items"]]
        self.assertIn(cls_prog["id"], prog_ids)
        self.assertNotIn(cls_prep["id"], prog_ids)

    def test_tc219_02_filter_program(self):
        """TC219-02: Lọc chương trình chỉ hiển thị lớp thuộc chương trình đào tạo đã chọn."""
        cls_p1 = self._create_class("P1", self.program_1.id)
        cls_p2 = self._create_class("P2", self.program_2.id)

        resp = self.client.get(f"/api/v1/classes?program_id={self.program_1.id}", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        items = resp.get_json()["data"]["items"]
        item_ids = [c["id"] for c in items]
        self.assertIn(cls_p1["id"], item_ids)
        self.assertNotIn(cls_p2["id"], item_ids)

    def test_tc219_03_filter_instructor_dependency(self):
        """TC219-03: Lọc giảng viên (chưa có assignment SCRUM-220 -> an toàn không crash, trả về mảng rỗng nếu chưa có)."""
        cls_1 = self._create_class("INST", self.program_1.id)

        resp = self.client.get(f"/api/v1/classes?instructor_id=some-unassigned-instructor", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        items = resp.get_json()["data"]["items"]
        item_ids = [c["id"] for c in items]
        # Do chưa có assignment nào nên lớp không được trả về
        self.assertNotIn(cls_1["id"], item_ids)

    def test_tc219_04_filter_date_range(self):
        """TC219-04: Lọc theo khoảng thời gian khai giảng dự kiến (expected_start_date)."""
        cls_may = self._create_class("MAY", self.program_1.id, start_date="2026-05-15")
        cls_aug = self._create_class("AUG", self.program_1.id, start_date="2026-08-20")
        cls_nov = self._create_class("NOV", self.program_1.id, start_date="2026-11-01")

        # Lọc từ 2026-06-01 đến 2026-09-30 -> chỉ có lớp tháng 8 (AUG)
        resp = self.client.get("/api/v1/classes?date_from=2026-06-01&date_to=2026-09-30", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        items = resp.get_json()["data"]["items"]
        item_ids = [c["id"] for c in items]
        self.assertIn(cls_aug["id"], item_ids)
        self.assertNotIn(cls_may["id"], item_ids)
        self.assertNotIn(cls_nov["id"], item_ids)

    def test_tc219_05_combined_filters(self):
        """TC219-05: Kết hợp nhiều bộ lọc đồng thời (status + program_id + date range)."""
        cls_match = self._create_class("MATCH", self.program_1.id, status="in_progress", start_date="2026-07-01")
        cls_diff_status = self._create_class("DIFFSTAT", self.program_1.id, status="preparing", start_date="2026-07-01")
        cls_diff_prog = self._create_class("DIFFPROG", self.program_2.id, status="in_progress", start_date="2026-07-01")
        cls_diff_date = self._create_class("DIFFDATE", self.program_1.id, status="in_progress", start_date="2026-12-01")

        query = f"/api/v1/classes?status=in_progress&program_id={self.program_1.id}&date_from=2026-06-01&date_to=2026-08-31"
        resp = self.client.get(query, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        items = resp.get_json()["data"]["items"]
        item_ids = [c["id"] for c in items]
        self.assertIn(cls_match["id"], item_ids)
        self.assertNotIn(cls_diff_status["id"], item_ids)
        self.assertNotIn(cls_diff_prog["id"], item_ids)
        self.assertNotIn(cls_diff_date["id"], item_ids)

    def test_tc219_06_reset_filters(self):
        """TC219-06: Xóa / bỏ filter -> trả về danh sách đầy đủ các lớp."""
        cls_1 = self._create_class("R1", self.program_1.id, status="preparing")
        cls_2 = self._create_class("R2", self.program_2.id, status="completed")

        resp = self.client.get("/api/v1/classes", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        items = resp.get_json()["data"]["items"]
        item_ids = [c["id"] for c in items]
        self.assertIn(cls_1["id"], item_ids)
        self.assertIn(cls_2["id"], item_ids)


if __name__ == "__main__":
    unittest.main()
