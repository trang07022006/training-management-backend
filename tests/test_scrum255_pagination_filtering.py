"""
Test suite cho tính năng phân trang, tìm kiếm và lọc danh sách buổi học hợp lệ (SCRUM-255).
"""

from datetime import date, datetime, timedelta, timezone
import json
import unittest
import uuid

from datetime import date, datetime, timedelta, timezone
import json
import unittest
import uuid

from flask_jwt_extended import create_access_token
from app.database.connection import get_db_connection
from app.main import app
from app.repositories.absence_request_repository import VIETNAM_TZ


class Scrum255PaginationFilteringTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = app.test_client()
        cls.suffix = uuid.uuid4().hex[:8]

        cls.admin_user_id = f"usr-adm-{cls.suffix}"
        cls.student_user_id = f"usr-stu-{cls.suffix}"
        cls.student_other_user_id = f"usr-oth-{cls.suffix}"
        cls.trainer_user_id = f"usr-trn-{cls.suffix}"

        cls.prog_id = f"prog-{cls.suffix}"
        cls.subject_1_id = f"sub1-{cls.suffix}"
        cls.subject_2_id = f"sub2-{cls.suffix}"
        cls.class_1_id = f"cls1-{cls.suffix}"
        cls.class_2_id = f"cls2-{cls.suffix}"
        cls.class_other_id = f"cls-oth-{cls.suffix}"

        cls.student_id = f"stu-{cls.suffix}"
        cls.student_other_id = f"stu-oth-{cls.suffix}"

        cls.schedule_ids = []

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Users
                cur.execute(
                    "INSERT INTO users (id, name, email, password_hash, status, created_at, updated_at) VALUES (%s, %s, %s, 'hash', 'active', NOW(), NOW())",
                    (cls.admin_user_id, f"Admin {cls.suffix}", f"admin_{cls.suffix}@test.com"),
                )
                cur.execute(
                    "INSERT INTO users (id, name, email, password_hash, status, created_at, updated_at) VALUES (%s, %s, %s, 'hash', 'active', NOW(), NOW())",
                    (cls.student_user_id, f"Student {cls.suffix}", f"student_{cls.suffix}@test.com"),
                )
                cur.execute(
                    "INSERT INTO users (id, name, email, password_hash, status, created_at, updated_at) VALUES (%s, %s, %s, 'hash', 'active', NOW(), NOW())",
                    (cls.student_other_user_id, f"Student Other {cls.suffix}", f"student_other_{cls.suffix}@test.com"),
                )
                cur.execute(
                    "INSERT INTO users (id, name, email, password_hash, status, created_at, updated_at) VALUES (%s, %s, %s, 'hash', 'active', NOW(), NOW())",
                    (cls.trainer_user_id, f"Trainer {cls.suffix}", f"trainer_{cls.suffix}@test.com"),
                )

                # Roles
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-admin', NOW())", (cls.admin_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.student_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.student_other_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.trainer_user_id,))

                # Students
                cur.execute(
                    "INSERT INTO students (id, user_id, student_code, full_name, email, phone, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, '0981111111', 'studying', NOW(), NOW())",
                    (cls.student_id, cls.student_user_id, f"STU-{cls.suffix}", f"Student {cls.suffix}", f"student_{cls.suffix}@test.com"),
                )
                cur.execute(
                    "INSERT INTO students (id, user_id, student_code, full_name, email, phone, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, '0982222222', 'studying', NOW(), NOW())",
                    (cls.student_other_id, cls.student_other_user_id, f"OTH-{cls.suffix}", f"Other {cls.suffix}", f"student_other_{cls.suffix}@test.com"),
                )

                # Training program
                cur.execute(
                    "INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'CTĐT Test', NOW(), NOW())",
                    (cls.prog_id, f"PRG-{cls.suffix}"),
                )

                # Subjects
                cur.execute(
                    "INSERT INTO subjects (id, code, name, credits, created_at, updated_at) VALUES (%s, %s, %s, 3, NOW(), NOW())",
                    (cls.subject_1_id, f"SUB1-{cls.suffix}", f"Lập trình Python {cls.suffix}"),
                )
                cur.execute(
                    "INSERT INTO subjects (id, code, name, credits, created_at, updated_at) VALUES (%s, %s, %s, 3, NOW(), NOW())",
                    (cls.subject_2_id, f"SUB2-{cls.suffix}", f"Cơ sở dữ liệu {cls.suffix}"),
                )

                # Classes
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, CURDATE() - INTERVAL 5 DAY, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_1_id, f"CLS1-{cls.suffix}", cls.prog_id),
                )
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, CURDATE() - INTERVAL 5 DAY, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_2_id, f"CLS2-{cls.suffix}", cls.prog_id),
                )
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, CURDATE() - INTERVAL 5 DAY, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_other_id, f"CLS-OTH-{cls.suffix}", cls.prog_id),
                )

                # Enrollments: student học class 1 và class 2
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', CURDATE() - INTERVAL 10 DAY, %s, NOW(), NOW())",
                    (f"enr-1-{cls.suffix}", cls.class_1_id, cls.student_id, cls.admin_user_id),
                )
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', CURDATE() - INTERVAL 10 DAY, %s, NOW(), NOW())",
                    (f"enr-2-{cls.suffix}", cls.class_2_id, cls.student_id, cls.admin_user_id),
                )
                # student_other học class_other
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', CURDATE() - INTERVAL 10 DAY, %s, NOW(), NOW())",
                    (f"enr-oth-{cls.suffix}", cls.class_other_id, cls.student_other_id, cls.admin_user_id),
                )

                # Tạo 25 buổi học hợp lệ:
                # 15 buổi cho Lớp 1 (Môn 1): từ ngày CURDATE() + 1 đến CURDATE() + 15
                for i in range(1, 16):
                    sch_id = f"sch1-{i:02d}-{cls.suffix}"
                    cls.schedule_ids.append(sch_id)
                    topic = f"Python bài học số {i}" if i != 5 else "Chủ đề đặc biệt KeywordTarget"
                    cur.execute(
                        """
                        INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, instructor_id, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, CURDATE() + INTERVAL %s DAY, 'Ca 1', '08:00:00', '10:00:00', 'scheduled', %s, NOW(), NOW())
                        """,
                        (sch_id, cls.class_1_id, cls.subject_1_id, i, topic, i, cls.trainer_user_id),
                    )

                # 10 buổi cho Lớp 2 (Môn 2): từ ngày CURDATE() + 16 đến CURDATE() + 25
                for i in range(1, 11):
                    sch_id = f"sch2-{i:02d}-{cls.suffix}"
                    cls.schedule_ids.append(sch_id)
                    cur.execute(
                        """
                        INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, instructor_id, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, CURDATE() + INTERVAL %s DAY, 'Ca 2', '13:30:00', '15:30:00', 'scheduled', %s, NOW(), NOW())
                        """,
                        (sch_id, cls.class_2_id, cls.subject_2_id, i, f"CSDL buổi {i}", 15 + i, cls.trainer_user_id),
                    )

                # 2 buổi cho Lớp khác (học viên không được thấy)
                cur.execute(
                    """
                    INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, instructor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, 1, 'Lớp khác không liên quan', CURDATE() + INTERVAL 1 DAY, 'Ca 1', '08:00:00', '10:00:00', 'scheduled', %s, NOW(), NOW())
                    """,
                    (f"sch-oth-1-{cls.suffix}", cls.class_other_id, cls.subject_1_id, cls.trainer_user_id),
                )
                cls.schedule_ids.append(f"sch-oth-1-{cls.suffix}")

            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM auth_sessions WHERE user_id IN (%s, %s, %s, %s)", (cls.admin_user_id, cls.student_user_id, cls.student_other_user_id, cls.trainer_user_id))
                cur.execute("DELETE FROM absence_request_attachments WHERE request_id IN (SELECT id FROM absence_requests WHERE schedule_id IN (%s))" % ",".join(["%s"] * len(cls.schedule_ids)), tuple(cls.schedule_ids))
                cur.execute("DELETE FROM absence_requests WHERE schedule_id IN (%s)" % ",".join(["%s"] * len(cls.schedule_ids)), tuple(cls.schedule_ids))
                cur.execute("DELETE FROM class_schedules WHERE id IN (%s)" % ",".join(["%s"] * len(cls.schedule_ids)), tuple(cls.schedule_ids))
                cur.execute("DELETE FROM class_enrollments WHERE class_id IN (%s, %s, %s)", (cls.class_1_id, cls.class_2_id, cls.class_other_id))
                cur.execute("DELETE FROM students WHERE id IN (%s, %s)", (cls.student_id, cls.student_other_id))
                cur.execute("DELETE FROM classes WHERE id IN (%s, %s, %s)", (cls.class_1_id, cls.class_2_id, cls.class_other_id))
                cur.execute("DELETE FROM subjects WHERE id IN (%s, %s)", (cls.subject_1_id, cls.subject_2_id))
                cur.execute("DELETE FROM training_programs WHERE id = %s", (cls.prog_id,))
                cur.execute("DELETE FROM user_roles WHERE user_id IN (%s, %s, %s, %s)", (cls.admin_user_id, cls.student_user_id, cls.student_other_user_id, cls.trainer_user_id))
                cur.execute("DELETE FROM users WHERE id IN (%s, %s, %s, %s)", (cls.admin_user_id, cls.student_user_id, cls.student_other_user_id, cls.trainer_user_id))
            conn.commit()
        finally:
            conn.close()

    def _get_auth_header(self, user_id: str) -> dict[str, str]:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO auth_sessions (session_id, user_id, refresh_jti, created_at, last_activity_at, idle_expires_at, absolute_expires_at)
                    VALUES (%s, %s, %s, NOW(), NOW(), DATE_ADD(NOW(), INTERVAL 8 HOUR), DATE_ADD(NOW(), INTERVAL 8 HOUR))
                    """,
                    (session_id, user_id, f"ref_{session_id}"),
                )
            conn.commit()
        finally:
            conn.close()

        with self.app.app_context():
            token = create_access_token(
                identity=user_id,
                additional_claims={"roles": ["trainee"], "sid": session_id},
            )
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def test_01_default_pagination_10_per_page(self):
        """Mặc định trả về 10 kết quả/trang, tổng cộng 25 buổi, 3 trang."""
        headers = self._get_auth_header(self.student_user_id)
        res = self.client.get("/api/v1/absence-requests/eligible-sessions?page=1&limit=10", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertIn("items", data)
        self.assertIn("pagination", data)
        self.assertIn("filter_options", data)

        items = data["items"]
        self.assertEqual(len(items), 10)

        pagination = data["pagination"]
        self.assertEqual(pagination["page"], 1)
        self.assertEqual(pagination["limit"], 10)
        self.assertEqual(pagination["total_items"], 25)
        self.assertEqual(pagination["total_pages"], 3)

    def test_02_pagination_no_duplicates_or_missing_across_pages(self):
        """Kiểm tra không bị trùng hoặc thiếu bản ghi khi duyệt qua các trang."""
        headers = self._get_auth_header(self.student_user_id)

        # Trang 1
        res1 = self.client.get("/api/v1/absence-requests/eligible-sessions?page=1&limit=10", headers=headers)
        items1 = res1.get_json()["data"]["items"]
        ids1 = [item["schedule_id"] for item in items1]

        # Trang 2
        res2 = self.client.get("/api/v1/absence-requests/eligible-sessions?page=2&limit=10", headers=headers)
        items2 = res2.get_json()["data"]["items"]
        ids2 = [item["schedule_id"] for item in items2]

        # Trang 3
        res3 = self.client.get("/api/v1/absence-requests/eligible-sessions?page=3&limit=10", headers=headers)
        items3 = res3.get_json()["data"]["items"]
        ids3 = [item["schedule_id"] for item in items3]

        self.assertEqual(len(items1), 10)
        self.assertEqual(len(items2), 10)
        self.assertEqual(len(items3), 5)

        # Tập hợp ID phải rời nhau hoàn toàn
        self.assertEqual(len(set(ids1).intersection(set(ids2))), 0)
        self.assertEqual(len(set(ids2).intersection(set(ids3))), 0)
        self.assertEqual(len(set(ids1).intersection(set(ids3))), 0)

        # Tổng hợp đủ 25 ID
        all_ids = set(ids1 + ids2 + ids3)
        self.assertEqual(len(all_ids), 25)

    def test_03_limit_20_per_page(self):
        """Tùy chọn hiển thị 20 kết quả/trang."""
        headers = self._get_auth_header(self.student_user_id)
        res = self.client.get("/api/v1/absence-requests/eligible-sessions?page=1&limit=20", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(len(data["items"]), 20)
        self.assertEqual(data["pagination"]["total_pages"], 2)

    def test_04_search_by_topic_keyword(self):
        """Tìm kiếm theo từ khóa chủ đề 'KeywordTarget'."""
        headers = self._get_auth_header(self.student_user_id)
        res = self.client.get("/api/v1/absence-requests/eligible-sessions?q=KeywordTarget", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["pagination"]["total_items"], 1)
        self.assertEqual(len(data["items"]), 1)
        self.assertIn("KeywordTarget", data["items"][0]["topic"])

    def test_05_search_by_class_code(self):
        """Tìm kiếm theo mã lớp CLS1."""
        headers = self._get_auth_header(self.student_user_id)
        res = self.client.get(f"/api/v1/absence-requests/eligible-sessions?q=CLS1-{self.suffix}", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["pagination"]["total_items"], 15)

    def test_06_filter_by_class_id(self):
        """Lọc theo class_id của Lớp 2."""
        headers = self._get_auth_header(self.student_user_id)
        res = self.client.get(f"/api/v1/absence-requests/eligible-sessions?class_id={self.class_2_id}", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["pagination"]["total_items"], 10)
        for item in data["items"]:
            self.assertEqual(item["class_id"], self.class_2_id)

    def test_07_filter_by_date_range(self):
        """Lọc theo khoảng ngày."""
        today = date.today()
        from_str = (today + timedelta(days=2)).isoformat()
        to_str = (today + timedelta(days=5)).isoformat()

        headers = self._get_auth_header(self.student_user_id)
        res = self.client.get(f"/api/v1/absence-requests/eligible-sessions?from_date={from_str}&to_date={to_str}", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        # Các ngày +2, +3, +4, +5 thuộc Lớp 1 -> tổng 4 buổi
        self.assertEqual(data["pagination"]["total_items"], 4)
        for item in data["items"]:
            self.assertTrue(from_str <= item["learning_date"] <= to_str)

    def test_08_filter_options_returned(self):
        """Kiểm tra danh sách options bộ lọc lớp và môn."""
        headers = self._get_auth_header(self.student_user_id)
        res = self.client.get("/api/v1/absence-requests/eligible-sessions?page=1&limit=10", headers=headers)
        self.assertEqual(res.status_code, 200)
        filter_options = res.get_json()["data"]["filter_options"]

        class_ids = [c["id"] for c in filter_options["classes"]]
        self.assertIn(self.class_1_id, class_ids)
        self.assertIn(self.class_2_id, class_ids)
        # Tuyệt đối không chứa lớp khác
        self.assertNotIn(self.class_other_id, class_ids)

        subject_ids = [s["id"] for s in filter_options["subjects"]]
        self.assertIn(self.subject_1_id, subject_ids)
        self.assertIn(self.subject_2_id, subject_ids)

    def test_09_permission_isolation_cannot_see_other_student_classes(self):
        """Học viên khác truy vấn không thấy buổi của lớp mà mình không ghi danh."""
        headers = self._get_auth_header(self.student_other_user_id)
        res = self.client.get("/api/v1/absence-requests/eligible-sessions?page=1&limit=10", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        # student_other chỉ có 1 buổi ở class_other
        self.assertEqual(data["pagination"]["total_items"], 1)
        self.assertEqual(data["items"][0]["class_id"], self.class_other_id)
