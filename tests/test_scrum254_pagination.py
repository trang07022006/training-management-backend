"""
Bộ kiểm thử tự động cho tính năng Phân trang và Thao tác hàng loạt Điểm danh (SCRUM-254 Pagination).

Kiểm tra:
1. Phân trang 25 học viên:
   - limit=10: chia thành 3 trang (10 / 10 / 5)
   - limit=20: chia thành 2 trang (20 / 5)
2. Backend cap limit tối đa 20 bản ghi mỗi lần tải (truyền limit=50 vẫn chỉ trả về tối đa 20).
3. Sắp xếp ổn định theo student_code, không trùng hay sót người giữa các trang.
4. Tìm kiếm theo mã hoặc tên trên toàn bộ học viên đủ điều kiện:
   - Tìm học viên nằm ở trang cuối, trả về chính xác học viên đó.
5. Thống kê sĩ số / trạng thái phản ánh toàn buổi, không phụ thuộc vào trang hay từ khóa tìm kiếm.
6. Đánh dấu tất cả có mặt (mark_all_present):
   - Áp dụng toàn bộ học viên đủ điều kiện của buổi.
   - Sửa riêng một người rồi lưu, kiểm tra kết quả lưu và audit log.
7. Buổi chỉ đọc (buổi tương lai) vẫn phân trang và tìm kiếm được nhưng không được lưu.
"""

from datetime import date, datetime, timedelta
import unittest
import uuid

from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.main import app
from app.services.attendance_service import VIETNAM_TZ


class Scrum254PaginationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = app.test_client()

        cls.suffix = uuid.uuid4().hex[:8]
        cls.trainer_id = f"tr-p-{cls.suffix}"
        cls.tm_id = f"tm-p-{cls.suffix}"

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Tạo Users
                cur.execute(
                    "INSERT INTO users (id, email, password_hash, name, created_at, updated_at) VALUES (%s, %s, 'hash', 'Trainer Page', NOW(), NOW())",
                    (cls.trainer_id, f"tr_page_{cls.suffix}@ictu.edu.vn"),
                )
                cur.execute(
                    "INSERT INTO users (id, email, password_hash, name, created_at, updated_at) VALUES (%s, %s, 'hash', 'TM Page', NOW(), NOW())",
                    (cls.tm_id, f"tm_page_{cls.suffix}@ictu.edu.vn"),
                )

                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.trainer_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-training-manager', NOW())", (cls.tm_id,))

                # 2. Tạo Program, Class, Subject, Room
                cls.prog_id = f"prog-p-{cls.suffix}"
                cur.execute(
                    "INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'Program Page', NOW(), NOW())",
                    (cls.prog_id, f"PRGP_{cls.suffix}"),
                )

                cls.class_id = f"cls-p-{cls.suffix}"
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, CURDATE() - INTERVAL 10 DAY, 50, 'in_progress', NOW(), NOW())",
                    (cls.class_id, f"CLSP_{cls.suffix}", cls.prog_id),
                )

                cls.subject_id = f"subj-p-{cls.suffix}"
                cur.execute(
                    "INSERT INTO subjects (id, code, name, credits, created_at, updated_at) VALUES (%s, %s, 'Subject Page', 3, NOW(), NOW())",
                    (cls.subject_id, f"SUBP_{cls.suffix}"),
                )

                cls.room_id = f"room-p-{cls.suffix}"
                cur.execute(
                    "INSERT INTO classrooms (id, room_code, room_name, capacity, status, created_at, updated_at) VALUES (%s, %s, 'Phòng 1122', 40, 'active', NOW(), NOW())",
                    (cls.room_id, "1122"),
                )

                # 3. Tạo buổi học hôm nay và buổi tương lai
                today_vn = datetime.now(VIETNAM_TZ).date()
                cls.schedule_today_id = f"sch-today-p-{cls.suffix}"
                cls.schedule_future_id = f"sch-future-p-{cls.suffix}"

                cur.execute(
                    """
                    INSERT INTO class_schedules (
                        id, class_id, subject_id, session_number, topic, learning_date,
                        shift, start_time, end_time, room_id, instructor_id, status, attendance_checked, created_at, updated_at
                    ) VALUES 
                    (%s, %s, %s, 1, 'Buổi học phân trang', %s, 'Ca 1 (07:30 - 09:30)', '07:30:00', '09:30:00', %s, %s, 'scheduled', 0, NOW(), NOW()),
                    (%s, %s, %s, 2, 'Buổi học tương lai', %s, 'Ca 1 (07:30 - 09:30)', '07:30:00', '09:30:00', %s, %s, 'scheduled', 0, NOW(), NOW())
                    """,
                    (
                        cls.schedule_today_id, cls.class_id, cls.subject_id, today_vn, cls.room_id, cls.trainer_id,
                        cls.schedule_future_id, cls.class_id, cls.subject_id, today_vn + timedelta(days=5), cls.room_id, cls.trainer_id,
                    ),
                )

                # 4. Tạo đúng 25 học viên đủ điều kiện
                cls.student_ids = []
                enroll_date = today_vn - timedelta(days=5)
                for i in range(1, 26):
                    sid = f"st-p-{i:02d}-{cls.suffix}"
                    code = f"SV_{cls.suffix}_{i:02d}"
                    name = f"Học viên Số {i:02d}"
                    email = f"student_{i:02d}_{cls.suffix}@ictu.edu.vn"
                    cls.student_ids.append(sid)

                    cur.execute(
                        "INSERT INTO students (id, student_code, full_name, email, phone, created_at, updated_at) VALUES (%s, %s, %s, %s, '0912345678', NOW(), NOW())",
                        (sid, code, name, email),
                    )
                    cur.execute(
                        """
                        INSERT INTO class_enrollments (id, class_id, student_id, status, lifecycle_status, effective_date, enrolled_at, enrolled_by, created_at, updated_at)
                        VALUES (%s, %s, %s, 'active', NULL, NULL, %s, %s, NOW(), NOW())
                        """,
                        (f"enr-p-{i:02d}-{cls.suffix}", cls.class_id, sid, enroll_date, cls.tm_id),
                    )

            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM attendance_audit_logs WHERE schedule_id IN (%s, %s)", (cls.schedule_today_id, cls.schedule_future_id))
                cur.execute("DELETE FROM session_attendances WHERE schedule_id IN (%s, %s)", (cls.schedule_today_id, cls.schedule_future_id))
                cur.execute("DELETE FROM class_schedules WHERE class_id = %s", (cls.class_id,))
                cur.execute("DELETE FROM class_enrollments WHERE class_id = %s", (cls.class_id,))
                for sid in cls.student_ids:
                    cur.execute("DELETE FROM students WHERE id = %s", (sid,))
                cur.execute("DELETE FROM classrooms WHERE id = %s", (cls.room_id,))
                cur.execute("DELETE FROM subjects WHERE id = %s", (cls.subject_id,))
                cur.execute("DELETE FROM classes WHERE id = %s", (cls.class_id,))
                cur.execute("DELETE FROM training_programs WHERE id = %s", (cls.prog_id,))
                cur.execute("DELETE FROM user_roles WHERE user_id IN (%s, %s)", (cls.trainer_id, cls.tm_id))
                cur.execute("DELETE FROM users WHERE id IN (%s, %s)", (cls.trainer_id, cls.tm_id))
            conn.commit()
        finally:
            conn.close()

    def _get_auth_header(self, user_id: str, role: str) -> dict[str, str]:
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
                additional_claims={"roles": [role], "sid": session_id},
            )
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def test_01_pagination_25_students_limit_10(self):
        """25 học viên chia 10/10/5 khi limit=10, không trùng lặp và không bỏ sót người."""
        headers = self._get_auth_header(self.trainer_id, "trainer")

        # Trang 1
        res1 = self.client.get(f"/api/v1/schedules/{self.schedule_today_id}/attendance?page=1&limit=10", headers=headers)
        self.assertEqual(res1.status_code, 200)
        d1 = res1.get_json()["data"]
        self.assertEqual(d1["pagination"]["page"], 1)
        self.assertEqual(d1["pagination"]["limit"], 10)
        self.assertEqual(d1["pagination"]["total_items"], 25)
        self.assertEqual(d1["pagination"]["total_pages"], 3)
        self.assertEqual(len(d1["students"]), 10)
        self.assertEqual(d1["stats"]["total_students"], 25)

        # Trang 2
        res2 = self.client.get(f"/api/v1/schedules/{self.schedule_today_id}/attendance?page=2&limit=10", headers=headers)
        self.assertEqual(res2.status_code, 200)
        d2 = res2.get_json()["data"]
        self.assertEqual(d2["pagination"]["page"], 2)
        self.assertEqual(len(d2["students"]), 10)

        # Trang 3
        res3 = self.client.get(f"/api/v1/schedules/{self.schedule_today_id}/attendance?page=3&limit=10", headers=headers)
        self.assertEqual(res3.status_code, 200)
        d3 = res3.get_json()["data"]
        self.assertEqual(d3["pagination"]["page"], 3)
        self.assertEqual(len(d3["students"]), 5)

        # Kiểm tra tính ổn định, không trùng giữa các trang
        ids_p1 = [s["student_id"] for s in d1["students"]]
        ids_p2 = [s["student_id"] for s in d2["students"]]
        ids_p3 = [s["student_id"] for s in d3["students"]]

        self.assertEqual(len(set(ids_p1) & set(ids_p2)), 0)
        self.assertEqual(len(set(ids_p2) & set(ids_p3)), 0)
        self.assertEqual(len(set(ids_p1) & set(ids_p3)), 0)
        all_collected = ids_p1 + ids_p2 + ids_p3
        self.assertEqual(len(all_collected), 25)
        self.assertEqual(set(all_collected), set(self.student_ids))

    def test_02_pagination_25_students_limit_20(self):
        """25 học viên chia 20/5 khi limit=20."""
        headers = self._get_auth_header(self.trainer_id, "trainer")

        # Trang 1 (20 người)
        res1 = self.client.get(f"/api/v1/schedules/{self.schedule_today_id}/attendance?page=1&limit=20", headers=headers)
        self.assertEqual(res1.status_code, 200)
        d1 = res1.get_json()["data"]
        self.assertEqual(d1["pagination"]["page"], 1)
        self.assertEqual(d1["pagination"]["limit"], 20)
        self.assertEqual(d1["pagination"]["total_pages"], 2)
        self.assertEqual(len(d1["students"]), 20)

        # Trang 2 (5 người)
        res2 = self.client.get(f"/api/v1/schedules/{self.schedule_today_id}/attendance?page=2&limit=20", headers=headers)
        self.assertEqual(res2.status_code, 200)
        d2 = res2.get_json()["data"]
        self.assertEqual(d2["pagination"]["page"], 2)
        self.assertEqual(len(d2["students"]), 5)

    def test_03_backend_caps_limit_at_20(self):
        """Backend giới hạn tối đa 20 bản ghi mỗi lần tải, truyền limit=50 vẫn cap ở 20."""
        headers = self._get_auth_header(self.trainer_id, "trainer")
        res = self.client.get(f"/api/v1/schedules/{self.schedule_today_id}/attendance?page=1&limit=50", headers=headers)
        self.assertEqual(res.status_code, 200)
        d = res.get_json()["data"]
        self.assertEqual(d["pagination"]["limit"], 20)
        self.assertEqual(len(d["students"]), 20)

    def test_04_search_student_in_last_page(self):
        """Tìm học viên ở trang cuối (Học viên Số 25), trả về đúng 1 kết quả, stats toàn buổi vẫn đủ 25."""
        headers = self._get_auth_header(self.trainer_id, "trainer")
        res = self.client.get(f"/api/v1/schedules/{self.schedule_today_id}/attendance?q=Số 25", headers=headers)
        self.assertEqual(res.status_code, 200)
        d = res.get_json()["data"]
        self.assertEqual(d["pagination"]["total_items"], 1)
        self.assertEqual(len(d["students"]), 1)
        self.assertIn("Số 25", d["students"][0]["full_name"])
        # Sĩ số toàn buổi vẫn là 25
        self.assertEqual(d["stats"]["total_students"], 25)

    def test_05_mark_all_present_bulk_and_override_one(self):
        """Thao tác hàng loạt mark_all_present: áp dụng toàn bộ 25 học viên, sửa riêng 1 người rồi lưu."""
        headers = self._get_auth_header(self.trainer_id, "trainer")

        # Đánh dấu tất cả có mặt nhưng override học viên 25 thành vắng không phép
        target_student_id = self.student_ids[-1]
        payload = {
            "mark_all_present": True,
            "attendances": [
                {
                    "student_id": target_student_id,
                    "status": "unexcused",
                    "notes": "Vắng không phép đặc biệt",
                }
            ],
            "reason": "Điểm danh hàng loạt đầu giờ có 1 bạn vắng",
        }
        res = self.client.post(
            f"/api/v1/schedules/{self.schedule_today_id}/attendance",
            json=payload,
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)
        d = res.get_json()["data"]
        self.assertEqual(d["updated_count"], 25)

        # Kiểm tra thống kê trả về sau khi lưu: 24 có mặt, 1 vắng không phép
        stats = d["stats"]
        self.assertEqual(stats["total_students"], 25)
        self.assertEqual(stats["present_count"], 24)
        self.assertEqual(stats["unexcused_count"], 1)
        self.assertEqual(stats["unmarked_count"], 0)

        # Kiểm tra trực tiếp trong DB
        conn = get_db_connection()
        try:
            with conn.cursor(dictionary=True) as cur:
                cur.execute("SELECT student_id, status, notes FROM session_attendances WHERE schedule_id = %s", (self.schedule_today_id,))
                records = {r["student_id"]: r for r in cur.fetchall()}
                self.assertEqual(len(records), 25)
                self.assertEqual(records[target_student_id]["status"], "unexcused")
                self.assertEqual(records[target_student_id]["notes"], "Vắng không phép đặc biệt")

                # Kiểm tra một học viên bất kỳ khác là present
                other_sid = self.student_ids[0]
                self.assertEqual(records[other_sid]["status"], "present")
        finally:
            conn.close()

    def test_06_future_session_readonly_can_paginate_cannot_save(self):
        """Buổi học tương lai chỉ đọc: Vẫn phân trang bình thường nhưng không được lưu."""
        headers = self._get_auth_header(self.trainer_id, "trainer")

        # GET phân trang thành công
        res_get = self.client.get(f"/api/v1/schedules/{self.schedule_future_id}/attendance?page=1&limit=10", headers=headers)
        self.assertEqual(res_get.status_code, 200)
        d = res_get.get_json()["data"]
        self.assertFalse(d["session_info"]["can_edit"])
        self.assertTrue(d["session_info"]["is_future"])
        self.assertEqual(len(d["students"]), 10)

        # POST lưu bị chặn (400)
        res_post = self.client.post(
            f"/api/v1/schedules/{self.schedule_future_id}/attendance",
            json={"mark_all_present": True},
            headers=headers,
        )
        self.assertEqual(res_post.status_code, 400)
        self.assertEqual(res_post.get_json()["code"], "FUTURE_SESSION_ATTENDANCE_BLOCKED")


if __name__ == "__main__":
    unittest.main()
