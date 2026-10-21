"""
Test suite chuyên sâu cho SCRUM-255: Chống gửi và duyệt đơn trùng lặp (Concurrency & Validation).
Kiểm thử các kịch bản bắt buộc:
1. Gửi lần đầu thành công.
2. Trùng Chờ duyệt (pending) bị chặn.
3. Trùng Đã duyệt (approved) bị chặn.
4. Hai yêu cầu gửi đồng thời (concurrent threads) chỉ tạo đúng 1 đơn hợp lệ, request còn lại bị chặn an toàn.
5. Duyệt đơn trùng đã tồn tại bị chặn, không thay đổi điểm danh / lịch sử.
6. Học viên khác hoặc buổi khác vẫn gửi được bình thường.
7. Gửi lại sau Từ chối (rejected) đúng quy tắc hiện có (nếu trong hạn 48 giờ).
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import unittest
import uuid

from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.database.ensure_business_roles import ensure_business_roles
from app.main import app
from app.models.login_session import LoginSession
from app.services import absence_request_service
from app.repositories import absence_request_repository


class Scrum255DuplicatePreventionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_business_roles()
        cls.now = datetime.now(timezone.utc)
        cls.suffix = uuid.uuid4().hex[:8]

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Users
                cls.trainer_id = f"test-tr-{cls.suffix}"
                cls.student_a_user_id = f"test-u-a-{cls.suffix}"
                cls.student_b_user_id = f"test-u-b-{cls.suffix}"
                cls.student_a_id = f"test-stu-a-{cls.suffix}"
                cls.student_b_id = f"test-stu-b-{cls.suffix}"

                for uid, name, email in [
                    (cls.trainer_id, "Trainer Dup", f"tr_{cls.suffix}@daotao.edu.vn"),
                    (cls.student_a_user_id, "Student A", f"stu_a_{cls.suffix}@daotao.edu.vn"),
                    (cls.student_b_user_id, "Student B", f"stu_b_{cls.suffix}@daotao.edu.vn"),
                ]:
                    cur.execute(
                        "INSERT INTO users (id, name, email, password_hash, role, status, created_at, updated_at) "
                        "VALUES (%s, %s, %s, 'hash', 'trainee', 'active', NOW(), NOW())",
                        (uid, name, email),
                    )

                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.trainer_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.student_a_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.student_b_user_id,))

                # 2. Program & Class & Subject
                cls.prog_id = f"prog-dup-{cls.suffix}"
                cur.execute("INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'Prog Dup', NOW(), NOW())", (cls.prog_id, f"PRG_{cls.suffix}"))
                cls.class_id = f"cls-dup-{cls.suffix}"
                cur.execute("INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, CURDATE() - INTERVAL 5 DAY, 30, 'in_progress', NOW(), NOW())", (cls.class_id, f"CL_{cls.suffix}", cls.prog_id))
                cls.subject_id = f"sub-dup-{cls.suffix}"
                cur.execute("INSERT INTO subjects (id, code, name, credits, created_at, updated_at) VALUES (%s, %s, 'Sub Dup', 3, NOW(), NOW())", (cls.subject_id, f"SB_{cls.suffix}"))

                # 3. Students
                cur.execute("INSERT INTO students (id, user_id, student_code, full_name, email, phone, status, created_at, updated_at) VALUES (%s, %s, %s, 'Student A', %s, '091', 'studying', NOW(), NOW())", (cls.student_a_id, cls.student_a_user_id, f"SA_{cls.suffix}", f"stu_a_{cls.suffix}@daotao.edu.vn"))
                cur.execute("INSERT INTO students (id, user_id, student_code, full_name, email, phone, status, created_at, updated_at) VALUES (%s, %s, %s, 'Student B', %s, '092', 'studying', NOW(), NOW())", (cls.student_b_id, cls.student_b_user_id, f"SB_{cls.suffix}", f"stu_b_{cls.suffix}@daotao.edu.vn"))

                # 4. Enrollments
                cur.execute("INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', CURDATE() - INTERVAL 5 DAY, %s, NOW(), NOW())", (f"enr-a-{cls.suffix}", cls.class_id, cls.student_a_id, cls.trainer_id))
                cur.execute("INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', CURDATE() - INTERVAL 5 DAY, %s, NOW(), NOW())", (f"enr-b-{cls.suffix}", cls.class_id, cls.student_b_id, cls.trainer_id))

                # 5. Schedules (Buổi 1 và Buổi 2)
                cls.sched_1_id = f"sch-1-{cls.suffix}"
                cls.sched_2_id = f"sch-2-{cls.suffix}"
                cur.execute(
                    "INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, attendance_checked, instructor_id, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 1, 'Buổi 1', CURDATE() + INTERVAL 2 DAY, 'Ca 1', '08:00:00', '10:00:00', 'scheduled', 0, %s, NOW(), NOW())",
                    (cls.sched_1_id, cls.class_id, cls.subject_id, cls.trainer_id),
                )
                cur.execute(
                    "INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, attendance_checked, instructor_id, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 2, 'Buổi 2', CURDATE() + INTERVAL 3 DAY, 'Ca 2', '10:00:00', '12:00:00', 'scheduled', 0, %s, NOW(), NOW())",
                    (cls.sched_2_id, cls.class_id, cls.subject_id, cls.trainer_id),
                )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM attendance_audit_logs WHERE student_id IN (%s, %s)", (cls.student_a_id, cls.student_b_id))
                cur.execute("DELETE FROM session_attendances WHERE student_id IN (%s, %s)", (cls.student_a_id, cls.student_b_id))
                cur.execute("DELETE FROM absence_request_attachments WHERE request_id IN (SELECT id FROM absence_requests WHERE student_id IN (%s, %s))", (cls.student_a_id, cls.student_b_id))
                cur.execute("DELETE FROM absence_requests WHERE student_id IN (%s, %s)", (cls.student_a_id, cls.student_b_id))
                cur.execute("DELETE FROM class_schedules WHERE class_id = %s", (cls.class_id,))
                cur.execute("DELETE FROM class_enrollments WHERE class_id = %s", (cls.class_id,))
                cur.execute("DELETE FROM students WHERE id IN (%s, %s)", (cls.student_a_id, cls.student_b_id))
                cur.execute("DELETE FROM classes WHERE id = %s", (cls.class_id,))
                cur.execute("DELETE FROM subjects WHERE id = %s", (cls.subject_id,))
                cur.execute("DELETE FROM training_programs WHERE id = %s", (cls.prog_id,))
                cur.execute("DELETE FROM auth_sessions WHERE user_id IN (%s, %s, %s)", (cls.trainer_id, cls.student_a_user_id, cls.student_b_user_id))
                cur.execute("DELETE FROM user_roles WHERE user_id IN (%s, %s, %s)", (cls.trainer_id, cls.student_a_user_id, cls.student_b_user_id))
                cur.execute("DELETE FROM users WHERE id IN (%s, %s, %s)", (cls.trainer_id, cls.student_a_user_id, cls.student_b_user_id))
            conn.commit()
        finally:
            conn.close()

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()

    def _get_auth_header(self, user_id: str, role: str) -> dict[str, str]:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO auth_sessions (session_id, user_id, refresh_jti, created_at, last_activity_at, idle_expires_at, absolute_expires_at) "
                    "VALUES (%s, %s, %s, NOW(), NOW(), DATE_ADD(NOW(), INTERVAL 8 HOUR), DATE_ADD(NOW(), INTERVAL 8 HOUR))",
                    (session_id, user_id, str(uuid.uuid4())),
                )
            conn.commit()
        finally:
            conn.close()

        with app.app_context():
            token = create_access_token(
                identity=user_id,
                additional_claims={"roles": [role], "sid": session_id},
            )
        return {"Authorization": f"Bearer {token}"}

    def test_01_submit_first_time_success(self):
        """1. Gửi lần đầu thành công."""
        headers_a = self._get_auth_header(self.student_a_user_id, "trainee")
        res = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": self.sched_1_id, "reason": "Em xin phép vắng buổi 1 lần đầu"},
            headers=headers_a,
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["schedule_id"], self.sched_1_id)

    def test_02_duplicate_pending_blocked(self):
        """2. Trùng Chờ duyệt (pending) bị chặn."""
        # Student A đã có đơn pending ở Buổi 1 từ test_01
        headers_a = self._get_auth_header(self.student_a_user_id, "trainee")
        res = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": self.sched_1_id, "reason": "Cố tình gửi thêm khi đang chờ duyệt"},
            headers=headers_a,
        )
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertEqual(body["code"], "DUPLICATE_PENDING_REQUEST")
        self.assertIn("đang chờ duyệt", body["message"])

    def test_03_duplicate_approved_blocked(self):
        """3. Trùng Đã duyệt (approved) bị chặn."""
        # Giảng viên duyệt đơn của Student A ở Buổi 1
        conn = get_db_connection()
        req_id = None
        try:
            with conn.cursor(dictionary=True) as cur:
                cur.execute("SELECT id FROM absence_requests WHERE student_id = %s AND schedule_id = %s", (self.student_a_id, self.sched_1_id))
                req_id = cur.fetchone()["id"]
        finally:
            conn.close()

        headers_tr = self._get_auth_header(self.trainer_id, "trainer")
        res_review = self.client.post(
            f"/api/v1/absence-requests/{req_id}/review",
            json={"action": "approve"},
            headers=headers_tr,
        )
        self.assertEqual(res_review.status_code, 200)

        # Bây giờ đơn đã approved -> Student A gửi lại Buổi 1 -> BỊ CHẶN DUPLICATE_APPROVED_REQUEST
        headers_a = self._get_auth_header(self.student_a_user_id, "trainee")
        res_dup = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": self.sched_1_id, "reason": "Gửi lại sau khi đơn đã được duyệt"},
            headers=headers_a,
        )
        self.assertEqual(res_dup.status_code, 400)
        body_dup = res_dup.get_json()
        self.assertEqual(body_dup["code"], "DUPLICATE_APPROVED_REQUEST")
        self.assertIn("đã có đơn xin phép vắng được phê duyệt", body_dup["message"])

    def test_04_concurrent_requests_only_one_succeeds(self):
        """4. Hai yêu cầu đồng thời chỉ tạo một đơn hợp lệ, request thứ hai bị chặn an toàn."""
        # Dùng Student B gửi 2 request đồng thời vào Buổi 2
        headers_b = self._get_auth_header(self.student_b_user_id, "trainee")

        def _send_request():
            with self.app.test_client() as c:
                return c.post(
                    "/api/v1/absence-requests",
                    json={"schedule_id": self.sched_2_id, "reason": "Xin phép vắng đồng thời concurrency"},
                    headers=headers_b,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(_send_request)
            future2 = executor.submit(_send_request)
            res1 = future1.result()
            res2 = future2.result()

        status_codes = sorted([res1.status_code, res2.status_code])
        # Đúng 1 request thành công 201, 1 request bị chặn 400
        self.assertEqual(status_codes, [201, 400])

        # Kiểm tra trong DB: Đúng 1 bản ghi được tạo
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM absence_requests WHERE student_id = %s AND schedule_id = %s", (self.student_b_id, self.sched_2_id))
                count = cur.fetchone()[0]
                self.assertEqual(count, 1)
        finally:
            conn.close()

    def test_05_block_approve_duplicate_when_already_approved(self):
        """5. Duyệt đơn trùng đã tồn tại bị chặn, không thay đổi điểm danh / lịch sử."""
        # Giả lập lọt thêm 1 đơn pending vào DB cho cùng student A và Buổi 1 (Buổi 1 vốn đã có đơn approved từ test_03)
        dup_req_id = f"ar-dup-{uuid.uuid4().hex[:8]}"
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO absence_requests (id, schedule_id, student_id, reason, status, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 'Đơn trùng lọt vào DB', 'pending', NOW(), NOW())",
                    (dup_req_id, self.sched_1_id, self.student_a_id),
                )
            conn.commit()
        finally:
            conn.close()

        # Đếm số audit logs ban đầu của student A
        initial_audit_count = 0
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM attendance_audit_logs WHERE schedule_id = %s AND student_id = %s", (self.sched_1_id, self.student_a_id))
                initial_audit_count = cur.fetchone()[0]
        finally:
            conn.close()

        headers_tr = self._get_auth_header(self.trainer_id, "trainer")
        res_approve_dup = self.client.post(
            f"/api/v1/absence-requests/{dup_req_id}/review",
            json={"action": "approve"},
            headers=headers_tr,
        )
        self.assertEqual(res_approve_dup.status_code, 400)
        self.assertEqual(res_approve_dup.get_json()["code"], "DUPLICATE_APPROVED_REQUEST")

        # Kiểm tra audit logs không bị tăng thêm
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM attendance_audit_logs WHERE schedule_id = %s AND student_id = %s", (self.sched_1_id, self.student_a_id))
                current_audit_count = cur.fetchone()[0]
                self.assertEqual(current_audit_count, initial_audit_count)
        finally:
            conn.close()

    def test_06_other_student_or_other_session_can_still_submit(self):
        """6. Học viên khác hoặc buổi khác vẫn gửi được."""
        # Student A gửi cho Buổi 2 (buổi khác)
        headers_a = self._get_auth_header(self.student_a_user_id, "trainee")
        res_a_sched2 = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": self.sched_2_id, "reason": "Student A xin nghỉ buổi 2"},
            headers=headers_a,
        )
        self.assertEqual(res_a_sched2.status_code, 201)

    def test_07_resubmit_after_rejection_allowed(self):
        """7. Gửi lại sau Từ chối (rejected) đúng quy tắc hiện có."""
        # Giảng viên từ chối đơn của Student A ở Buổi 2
        conn = get_db_connection()
        req_a_sched2_id = None
        try:
            with conn.cursor(dictionary=True) as cur:
                cur.execute("SELECT id FROM absence_requests WHERE student_id = %s AND schedule_id = %s AND status = 'pending'", (self.student_a_id, self.sched_2_id))
                req_a_sched2_id = cur.fetchone()["id"]
        finally:
            conn.close()

        headers_tr = self._get_auth_header(self.trainer_id, "trainer")
        res_reject = self.client.post(
            f"/api/v1/absence-requests/{req_a_sched2_id}/review",
            json={"action": "reject", "rejection_reason": "Từ chối vì chưa đủ lý do"},
            headers=headers_tr,
        )
        self.assertEqual(res_reject.status_code, 200)

        # Sau khi bị từ chối, Student A gửi lại đơn mới cho Buổi 2 -> THÀNH CÔNG (201)
        headers_a = self._get_auth_header(self.student_a_user_id, "trainee")
        res_resubmit = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": self.sched_2_id, "reason": "Bổ sung lý do chi tiết sau khi bị từ chối"},
            headers=headers_a,
        )
        self.assertEqual(res_resubmit.status_code, 201)
        self.assertEqual(res_resubmit.get_json()["data"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
