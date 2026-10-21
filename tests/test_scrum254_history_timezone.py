"""
Bộ kiểm thử tự động cho SCRUM-254: Định dạng múi giờ lịch sử điểm danh (ISO 8601 UTC).

Kiểm thử:
1. Hàm format_utc_timestamp_iso định dạng chuẩn naive datetime sang ISO 8601 UTC kết thúc bằng 'Z'.
2. API GET /api/v1/schedules/<id>/attendance/history trả về created_at có múi giờ rõ ràng (hậu tố 'Z').
3. Thứ tự lịch sử: sắp xếp giảm dần theo created_at (mới nhất lên đầu).
4. Thao tác sửa mới thực tế:
   - Sửa trạng thái học viên từ 'late' (Đi muộn) sang 'excused' (Vắng có phép).
   - Kiểm tra audit log mới sinh ra có old_status='late', new_status='excused'.
   - Audit log mới xuất hiện đầu tiên với created_at chuẩn UTC kết thúc bằng 'Z'.
5. Bảo toàn bản ghi lịch sử hiện có (không sửa đổi dữ liệu DB cũ, API vẫn serialize chuẩn UTC).
"""

from datetime import datetime, timezone
import unittest
import uuid

from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.main import app
from app.services.attendance_service import format_utc_timestamp_iso, VIETNAM_TZ


class Scrum254HistoryTimezoneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = app.test_client()
        cls.suffix = uuid.uuid4().hex[:8]

        cls.trainer_id = f"test-tr-tz-{cls.suffix}"
        cls.student_id = f"test-stu-tz-{cls.suffix}"
        cls.student_code = f"STU{cls.suffix[:6].upper()}"

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Tạo user trainer
                cur.execute(
                    "INSERT INTO users (id, email, password_hash, name, created_at, updated_at) VALUES (%s, %s, 'hash', %s, NOW(), NOW())",
                    (cls.trainer_id, f"trainer_tz_{cls.suffix}@ictu.edu.vn", "Giàng A Tùng"),
                )
                cur.execute(
                    "INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())",
                    (cls.trainer_id,),
                )

                # 2. Tạo Program, Class, Subject, Room
                cls.prog_id = f"prog-tz-{cls.suffix}"
                cur.execute(
                    "INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'Program SCRUM-254 TZ', NOW(), NOW())",
                    (cls.prog_id, f"PRG_TZ_{cls.suffix}"),
                )

                cls.class_id = f"cls-tz-{cls.suffix}"
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, CURDATE(), 30, 'in_progress', NOW(), NOW())",
                    (cls.class_id, f"CLS_TZ_{cls.suffix}", cls.prog_id),
                )

                cls.subject_id = f"subj-tz-{cls.suffix}"
                cur.execute(
                    "INSERT INTO subjects (id, code, name, credits, created_at, updated_at) VALUES (%s, %s, 'Subject TZ', 3, NOW(), NOW())",
                    (cls.subject_id, f"SUB_TZ_{cls.suffix}"),
                )

                cls.room_id = f"room-tz-{cls.suffix}"
                cur.execute(
                    "INSERT INTO classrooms (id, room_code, room_name, capacity, status, created_at, updated_at) VALUES (%s, %s, 'Phòng 101', 40, 'active', NOW(), NOW())",
                    (cls.room_id, f"R101_{cls.suffix}"),
                )

                # 3. Tạo Schedule hôm nay theo giờ Việt Nam (UTC+7)
                today_vn = datetime.now(VIETNAM_TZ).date()
                cls.schedule_id = f"sch-tz-{cls.suffix}"
                cur.execute(
                    """
                    INSERT INTO class_schedules 
                    (id, class_id, subject_id, room_id, instructor_id, session_number, topic, shift, learning_date, start_time, end_time, status, attendance_checked, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 1, 'Chủ đề TZ', 'Sáng', %s, '08:00:00', '11:30:00', 'scheduled', 0, NOW(), NOW())
                    """,
                    (cls.schedule_id, cls.class_id, cls.subject_id, cls.room_id, cls.trainer_id, today_vn),
                )

                # 4. Tạo Student & Enrollment
                cur.execute(
                    "INSERT INTO students (id, student_code, full_name, email, phone, created_at, updated_at) VALUES (%s, %s, 'Nguyễn Văn Minh', %s, '0987654321', NOW(), NOW())",
                    (cls.student_id, cls.student_code, f"stu_{cls.suffix}@student.edu.vn"),
                )
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'active', CURDATE(), %s, NOW(), NOW())",
                    (f"enr-tz-{cls.suffix}", cls.class_id, cls.student_id, cls.trainer_id),
                )
                conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM attendance_audit_logs WHERE schedule_id = %s", (cls.schedule_id,))
                cur.execute("DELETE FROM session_attendances WHERE schedule_id = %s", (cls.schedule_id,))
                cur.execute("DELETE FROM class_schedules WHERE id = %s", (cls.schedule_id,))
                cur.execute("DELETE FROM class_enrollments WHERE class_id = %s", (cls.class_id,))
                cur.execute("DELETE FROM students WHERE id = %s", (cls.student_id,))
                cur.execute("DELETE FROM classrooms WHERE id = %s", (cls.room_id,))
                cur.execute("DELETE FROM subjects WHERE id = %s", (cls.subject_id,))
                cur.execute("DELETE FROM classes WHERE id = %s", (cls.class_id,))
                cur.execute("DELETE FROM training_programs WHERE id = %s", (cls.prog_id,))
                cur.execute("DELETE FROM auth_sessions WHERE user_id = %s", (cls.trainer_id,))
                cur.execute("DELETE FROM user_roles WHERE user_id = %s", (cls.trainer_id,))
                cur.execute("DELETE FROM users WHERE id = %s", (cls.trainer_id,))
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

    def test_01_format_utc_timestamp_iso_unit(self):
        """Kiểm tra logic hàm format_utc_timestamp_iso chuẩn hóa sang ISO 8601 UTC có Z."""
        # 1. Naive datetime từ DB
        dt_naive = datetime(2026, 10, 19, 17, 25, 22, 233764)
        iso = format_utc_timestamp_iso(dt_naive)
        self.assertEqual(iso, "2026-10-19T17:25:22.233764Z")

        # 2. Datetime đã có tzinfo UTC
        dt_utc = datetime(2026, 10, 19, 17, 25, 22, tzinfo=timezone.utc)
        iso_utc = format_utc_timestamp_iso(dt_utc)
        self.assertEqual(iso_utc, "2026-10-19T17:25:22Z")

        # 3. Chuỗi naive legacy chưa có Z
        self.assertEqual(format_utc_timestamp_iso("2026-10-19 17:25:22"), "2026-10-19T17:25:22Z")
        self.assertEqual(format_utc_timestamp_iso("2026-10-19T17:25:22.233764"), "2026-10-19T17:25:22.233764Z")

        # 4. Chuỗi đã có Z
        self.assertEqual(format_utc_timestamp_iso("2026-10-19T17:25:22.233764Z"), "2026-10-19T17:25:22.233764Z")

        # 5. Dữ liệu None
        self.assertIsNone(format_utc_timestamp_iso(None))

    def test_02_live_attendance_edit_and_audit_timezone(self):
        """
        Thao tác sửa mới thực tế:
        - Điểm danh ban đầu: Đi muộn (late)
        - Sửa sang: Vắng có phép (excused) lúc nửa đêm
        - Kiểm tra audit log:
          1. old_status = 'late', new_status = 'excused'
          2. created_at trả về kết thúc bằng 'Z' (ISO 8601 UTC)
          3. Sắp xếp giảm dần theo thời gian (mới nhất lên đầu)
        """
        headers = self._get_auth_header(self.trainer_id, "trainer")

        # Bước 1: Lưu lần đầu STU000764 = late (Đi muộn)
        res1 = self.client.post(
            f"/api/v1/schedules/{self.schedule_id}/attendance",
            json={
                "attendances": [{"student_id": self.student_id, "status": "late", "notes": "Đến muộn 15p"}],
            },
            headers=headers,
        )
        self.assertEqual(res1.status_code, 200)

        # Bước 2: Thực hiện thao tác sửa mới thực tế như mô tả sự cố:
        # Sửa STU000764 từ 'late' sang 'excused' kèm lý do
        res2 = self.client.post(
            f"/api/v1/schedules/{self.schedule_id}/attendance",
            json={
                "attendances": [{"student_id": self.student_id, "status": "excused", "notes": "Phụ huynh xin phép muộn"}],
                "reason": "Phụ huynh gửi đơn xin phép muộn",
            },
            headers=headers,
        )
        self.assertEqual(res2.status_code, 200)

        # Bước 3: Gọi API lấy lịch sử kiểm toán điểm danh
        res_hist = self.client.get(
            f"/api/v1/schedules/{self.schedule_id}/attendance/history",
            headers=headers,
        )
        self.assertEqual(res_hist.status_code, 200)
        logs = res_hist.get_json()["data"]
        self.assertIsInstance(logs, list)
        self.assertGreaterEqual(len(logs), 2)

        # Bản ghi mới nhất phải ở đầu danh sách (DESC)
        latest_log = logs[0]
        self.assertEqual(latest_log["student_id"], self.student_id)
        self.assertEqual(latest_log["old_status"], "late")
        self.assertEqual(latest_log["new_status"], "excused")
        self.assertEqual(latest_log["reason"], "Phụ huynh gửi đơn xin phép muộn")
        self.assertEqual(latest_log["performed_by"], self.trainer_id)

        # Quan trọng: created_at phải có múi giờ rõ ràng (kết thúc bằng 'Z')
        created_at_str = latest_log["created_at"]
        self.assertTrue(created_at_str.endswith("Z"), f"created_at '{created_at_str}' phải kết thúc bằng 'Z'")
        self.assertIn("T", created_at_str)

        # Bản ghi cũ hơn (lần 1)
        older_log = logs[1]
        self.assertIsNone(older_log["old_status"])
        self.assertEqual(older_log["new_status"], "late")
        self.assertTrue(older_log["created_at"].endswith("Z"))

        # Kiểm tra thứ tự thời gian giảm dần (latest >= older)
        self.assertGreaterEqual(latest_log["created_at"], older_log["created_at"])

    def test_03_sheet_updated_at_has_z_suffix(self):
        """Kiểm tra trường updated_at trong sổ điểm danh cũng được format UTC có 'Z' rõ ràng."""
        headers = self._get_auth_header(self.trainer_id, "trainer")
        res = self.client.get(
            f"/api/v1/schedules/{self.schedule_id}/attendance",
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)
        sheet_data = res.get_json()["data"]
        students = sheet_data.get("students", [])
        self.assertGreaterEqual(len(students), 1)

        st = next(s for s in students if s["student_id"] == self.student_id)
        self.assertIsNotNone(st.get("updated_at"))
        self.assertTrue(st["updated_at"].endswith("Z"), f"updated_at '{st['updated_at']}' phải kết thúc bằng 'Z'")

    def test_04_preserve_legacy_history_record_with_explicit_utc_serialization(self):
        """
        Bảo toàn bản ghi lịch sử hiện có:
        - Giả lập bản ghi lịch sử đã tồn tại trong DB với kiểu DATETIME(6) cũ (không timezone)
        - Khi API trả về, bản ghi vẫn được serialize chuẩn UTC kèm 'Z' mà không làm sai lệch hay sửa đổi dữ liệu gốc
        """
        # Chèn trực tiếp một audit log giả lập bản ghi cũ từ trước
        legacy_log_id = f"aal-legacy-{self.suffix}"
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO attendance_audit_logs 
                    (id, schedule_id, student_id, old_status, new_status, reason, performed_by, created_at)
                    VALUES (%s, %s, %s, 'present', 'late', 'Bản ghi lịch sử cũ', %s, '2026-10-19 10:15:30.123456')
                    """,
                    (legacy_log_id, self.schedule_id, self.student_id, self.trainer_id),
                )
                conn.commit()
        finally:
            conn.close()

        headers = self._get_auth_header(self.trainer_id, "trainer")
        res = self.client.get(
            f"/api/v1/schedules/{self.schedule_id}/attendance/history",
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)
        logs = res.get_json()["data"]
        legacy_log = next((l for l in logs if l["id"] == legacy_log_id), None)
        self.assertIsNotNone(legacy_log)
        self.assertEqual(legacy_log["old_status"], "present")
        self.assertEqual(legacy_log["new_status"], "late")
        self.assertEqual(legacy_log["created_at"], "2026-10-19T10:15:30.123456Z")


if __name__ == "__main__":
    unittest.main()

