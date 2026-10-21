"""
Bộ kiểm thử tự động cho SCRUM-255 Lát cắt 255.1 — Học viên gửi và theo dõi đơn xin phép vắng.
Kiểm tra:
1. Danh sách buổi học đủ điều kiện gửi đơn:
   - Chỉ trả về các buổi học hợp lệ (lớp đang học, không bị huỷ, chưa quá 48h sau kết thúc).
   - Admin thuần túy hoặc tài khoản không có hồ sơ học viên bị từ chối (403).
2. Gửi đơn xin phép vắng:
   - Lý do hợp lệ -> tạo đơn thành công với trạng thái Chờ duyệt (pending).
   - Lý do rỗng, toàn khoảng trắng, < 5 ký tự, > 1000 ký tự -> chặn với mã lỗi tương ứng.
   - Buổi học không tồn tại, buổi của lớp khác, buổi đã hủy -> chặn (400).
   - Gửi lặp khi đã có đơn pending cho cùng buổi học -> chặn (400 DUPLICATE_PENDING_REQUEST).
   - Gửi lại sau khi bị từ chối (rejected) -> cho phép tạo đơn mới thành công (201).
   - Giả mạo student_id trong payload -> API chỉ lấy từ JWT identity của chính người gửi.
3. Xem danh sách đơn cá nhân:
   - Phân trang chuẩn, lọc theo trạng thái, tìm kiếm.
   - Không rò rỉ đơn của học viên khác.
4. Xem chi tiết đơn:
   - Chính chủ xem được đơn của mình (200).
   - Học viên khác không có quyền truy cập (403).
"""

from datetime import date, datetime, timedelta
import unittest
import uuid

from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.main import app
from app.repositories.absence_request_repository import VIETNAM_TZ


class Scrum255Slice1AbsenceRequestsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = app.test_client()

        cls.suffix = uuid.uuid4().hex[:8]
        cls.admin_user_id = f"test-admin-{cls.suffix}"
        cls.student_a_user_id = f"test-u-stu-a-{cls.suffix}"
        cls.student_b_user_id = f"test-u-stu-b-{cls.suffix}"
        cls.student_a_id = f"test-stu-a-{cls.suffix}"
        cls.student_b_id = f"test-stu-b-{cls.suffix}"
        cls.trainer_user_id = f"test-tr-{cls.suffix}"

        cls.created_user_ids = [cls.admin_user_id, cls.student_a_user_id, cls.student_b_user_id, cls.trainer_user_id]
        cls.created_student_ids = [cls.student_a_id, cls.student_b_id]

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Tạo users
                users = [
                    (cls.admin_user_id, f"admin_{cls.suffix}@daotao.edu.vn", "Admin User"),
                    (cls.student_a_user_id, f"student_a_{cls.suffix}@daotao.edu.vn", "Student A"),
                    (cls.student_b_user_id, f"student_b_{cls.suffix}@daotao.edu.vn", "Student B"),
                    (cls.trainer_user_id, f"trainer_{cls.suffix}@daotao.edu.vn", "Trainer User"),
                ]
                for uid, email, name in users:
                    cur.execute(
                        "INSERT INTO users (id, email, password_hash, name, created_at, updated_at) VALUES (%s, %s, 'hash', %s, NOW(), NOW())",
                        (uid, email, name),
                    )

                # Gán roles
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-admin', NOW())", (cls.admin_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.student_a_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.student_b_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.trainer_user_id,))

                # 2. Tạo Program, Class A, Class B, Subject
                cls.prog_id = f"prog-{cls.suffix}"
                cur.execute(
                    "INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'Program 255', NOW(), NOW())",
                    (cls.prog_id, f"PRG_{cls.suffix}"),
                )

                cls.class_a_id = f"cls-a-{cls.suffix}"
                cls.class_b_id = f"cls-b-{cls.suffix}"
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, CURDATE() - INTERVAL 5 DAY, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_a_id, f"CLA_{cls.suffix}", cls.prog_id),
                )
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, CURDATE() - INTERVAL 5 DAY, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_b_id, f"CLB_{cls.suffix}", cls.prog_id),
                )

                cls.subject_id = f"sub-{cls.suffix}"
                cur.execute(
                    "INSERT INTO subjects (id, code, name, credits, created_at, updated_at) VALUES (%s, %s, 'Subject 255', 3, NOW(), NOW())",
                    (cls.subject_id, f"SUB_{cls.suffix}"),
                )

                # 3. Tạo học viên
                cur.execute(
                    "INSERT INTO students (id, user_id, student_code, full_name, email, phone, status, created_at, updated_at) VALUES (%s, %s, %s, 'Student A', %s, '0981111111', 'studying', NOW(), NOW())",
                    (cls.student_a_id, cls.student_a_user_id, f"STU_A_{cls.suffix}", f"student_a_{cls.suffix}@daotao.edu.vn"),
                )
                cur.execute(
                    "INSERT INTO students (id, user_id, student_code, full_name, email, phone, status, created_at, updated_at) VALUES (%s, %s, %s, 'Student B', %s, '0982222222', 'studying', NOW(), NOW())",
                    (cls.student_b_id, cls.student_b_user_id, f"STU_B_{cls.suffix}", f"student_b_{cls.suffix}@daotao.edu.vn"),
                )

                # 4. Ghi danh: Học viên A vào Lớp A, Học viên B vào Lớp B
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', CURDATE() - INTERVAL 5 DAY, %s, NOW(), NOW())",
                    (f"enr-a-{cls.suffix}", cls.class_a_id, cls.student_a_id, cls.admin_user_id),
                )
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', CURDATE() - INTERVAL 5 DAY, %s, NOW(), NOW())",
                    (f"enr-b-{cls.suffix}", cls.class_b_id, cls.student_b_id, cls.admin_user_id),
                )

                # 5. Tạo các buổi học kiểm thử cho Lớp A
                # Buổi 1: Hôm nay (hợp lệ)
                cls.sched_today_id = f"sch-today-{cls.suffix}"
                cur.execute(
                    """
                    INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, instructor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, 1, 'Buổi học hôm nay', CURDATE(), 'Ca 1', '08:00:00', '10:00:00', 'scheduled', %s, NOW(), NOW())
                    """,
                    (cls.sched_today_id, cls.class_a_id, cls.subject_id, cls.trainer_user_id),
                )

                # Buổi 2: Tương lai (hợp lệ)
                cls.sched_future_id = f"sch-future-{cls.suffix}"
                cur.execute(
                    """
                    INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, instructor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, 2, 'Buổi học tương lai', CURDATE() + INTERVAL 2 DAY, 'Ca 2', '13:30:00', '15:30:00', 'scheduled', %s, NOW(), NOW())
                    """,
                    (cls.sched_future_id, cls.class_a_id, cls.subject_id, cls.trainer_user_id),
                )

                # Buổi 3: Đã hủy (không được phép gửi đơn)
                cls.sched_cancelled_id = f"sch-canc-{cls.suffix}"
                cur.execute(
                    """
                    INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, cancellation_reason, instructor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, 3, 'Buổi học đã hủy', CURDATE() + INTERVAL 3 DAY, 'Ca 1', '08:00:00', '10:00:00', 'cancelled', 'Nghỉ lễ', %s, NOW(), NOW())
                    """,
                    (cls.sched_cancelled_id, cls.class_a_id, cls.subject_id, cls.trainer_user_id),
                )

                # Buổi 4: Quá khứ xa > 48h (hết hạn gửi đơn)
                cls.sched_expired_id = f"sch-exp-{cls.suffix}"
                cur.execute(
                    """
                    INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, instructor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, 4, 'Buổi quá hạn', CURDATE() - INTERVAL 4 DAY, 'Ca 1', '08:00:00', '10:00:00', 'scheduled', %s, NOW(), NOW())
                    """,
                    (cls.sched_expired_id, cls.class_a_id, cls.subject_id, cls.trainer_user_id),
                )

                # Buổi 5: Thuộc Lớp B (học viên A không theo học)
                cls.sched_class_b_id = f"sch-clb-{cls.suffix}"
                cur.execute(
                    """
                    INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, instructor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, 1, 'Buổi của Lớp B', CURDATE(), 'Ca 1', '08:00:00', '10:00:00', 'scheduled', %s, NOW(), NOW())
                    """,
                    (cls.sched_class_b_id, cls.class_b_id, cls.subject_id, cls.trainer_user_id),
                )

            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM auth_sessions WHERE user_id IN (%s, %s, %s, %s)", (cls.admin_user_id, cls.student_a_user_id, cls.student_b_user_id, cls.trainer_user_id))
                cur.execute("DELETE FROM absence_request_attachments WHERE request_id IN (SELECT id FROM absence_requests WHERE schedule_id IN (%s, %s, %s, %s, %s))", (cls.sched_today_id, cls.sched_future_id, cls.sched_cancelled_id, cls.sched_expired_id, cls.sched_class_b_id))
                cur.execute("DELETE FROM absence_requests WHERE schedule_id IN (%s, %s, %s, %s, %s)", (cls.sched_today_id, cls.sched_future_id, cls.sched_cancelled_id, cls.sched_expired_id, cls.sched_class_b_id))
                cur.execute("DELETE FROM class_schedules WHERE id IN (%s, %s, %s, %s, %s)", (cls.sched_today_id, cls.sched_future_id, cls.sched_cancelled_id, cls.sched_expired_id, cls.sched_class_b_id))
                cur.execute("DELETE FROM class_enrollments WHERE class_id IN (%s, %s)", (cls.class_a_id, cls.class_b_id))
                cur.execute("DELETE FROM students WHERE id IN (%s, %s)", (cls.student_a_id, cls.student_b_id))
                cur.execute("DELETE FROM classes WHERE id IN (%s, %s)", (cls.class_a_id, cls.class_b_id))
                cur.execute("DELETE FROM subjects WHERE id = %s", (cls.subject_id,))
                cur.execute("DELETE FROM training_programs WHERE id = %s", (cls.prog_id,))
                cur.execute("DELETE FROM user_roles WHERE user_id IN (%s, %s, %s, %s)", (cls.admin_user_id, cls.student_a_user_id, cls.student_b_user_id, cls.trainer_user_id))
                cur.execute("DELETE FROM users WHERE id IN (%s, %s, %s, %s)", (cls.admin_user_id, cls.student_a_user_id, cls.student_b_user_id, cls.trainer_user_id))
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

    def test_01_eligible_sessions_list(self):
        """Học viên A lấy danh sách buổi học hợp lệ để chọn xin phép vắng."""
        headers = self._get_auth_header(self.student_a_user_id, "trainee")
        res = self.client.get(
            "/api/v1/absence-requests/eligible-sessions",
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        sched_ids = [s["schedule_id"] for s in data]

        # Phải chứa buổi hôm nay và tương lai của Lớp A
        self.assertIn(self.sched_today_id, sched_ids)
        self.assertIn(self.sched_future_id, sched_ids)

        # Tuyệt đối không chứa buổi đã hủy, buổi quá hạn 48h, hoặc buổi của lớp khác
        self.assertNotIn(self.sched_cancelled_id, sched_ids)
        self.assertNotIn(self.sched_expired_id, sched_ids)
        self.assertNotIn(self.sched_class_b_id, sched_ids)

    def test_02_admin_forbidden_to_access_eligible_sessions(self):
        """Admin thuần túy không có quyền truy cập danh sách buổi học xin phép vắng."""
        headers = self._get_auth_header(self.admin_user_id, "admin")
        res = self.client.get(
            "/api/v1/absence-requests/eligible-sessions",
            headers=headers,
        )
        self.assertEqual(res.status_code, 403)

    def test_03_submit_absence_request_validation_errors(self):
        """Kiểm tra chặn các trường hợp lý do không hợp lệ."""
        headers = self._get_auth_header(self.student_a_user_id, "trainee")
        # 1. Lý do rỗng
        res = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": self.sched_today_id, "reason": ""},
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "REASON_REQUIRED")

        # 2. Lý do chỉ chứa khoảng trắng
        res = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": self.sched_today_id, "reason": "   \n\t  "},
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "REASON_REQUIRED")

        # 3. Lý do quá ngắn (< 5 ký tự)
        res = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": self.sched_today_id, "reason": "Bận"},
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "REASON_TOO_SHORT")

        # 4. Lý do quá dài (> 1000 ký tự)
        res = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": self.sched_today_id, "reason": "A" * 1001},
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "REASON_TOO_LONG")

        # 5. Thiếu schedule_id
        res = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": "", "reason": "Em bị ốm phải đi khám bác sĩ"},
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "SCHEDULE_ID_REQUIRED")

    def test_04_submit_absence_request_ineligible_sessions(self):
        """Kiểm tra chặn gửi đơn cho buổi không hợp lệ."""
        headers = self._get_auth_header(self.student_a_user_id, "trainee")
        # 1. Buổi học không tồn tại
        res = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": "non-existent-id", "reason": "Em có việc bận gia đình"},
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "SESSION_NOT_ELIGIBLE")

        # 2. Buổi của lớp khác (học viên A gửi cho Lớp B)
        res = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": self.sched_class_b_id, "reason": "Em có việc bận gia đình"},
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "SESSION_NOT_ELIGIBLE")

        # 3. Buổi đã hủy
        res = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": self.sched_cancelled_id, "reason": "Em có việc bận gia đình"},
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "SESSION_NOT_ELIGIBLE")

        # 4. Buổi quá hạn 48 giờ
        res = self.client.post(
            "/api/v1/absence-requests",
            json={"schedule_id": self.sched_expired_id, "reason": "Em có việc bận gia đình"},
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "SESSION_NOT_ELIGIBLE")

    def test_05_submit_absence_request_success_and_duplicate_block(self):
        """Gửi đơn thành công, chặn gửi lặp khi đang pending, cho phép gửi lại sau khi rejected."""
        headers = self._get_auth_header(self.student_a_user_id, "trainee")
        # 1. Gửi đơn hợp lệ lần đầu
        res = self.client.post(
            "/api/v1/absence-requests",
            json={
                "schedule_id": self.sched_today_id,
                "reason": "Em bị sốt cao cần đi viện kiểm tra.",
                "student_id": "fake-student-id", # Client cố ý giả mạo student_id -> API phải bỏ qua và dùng ID thật
            },
            headers=headers,
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["student_id"], self.student_a_id) # Không bị giả mạo
        request_id = data["id"]

        # 2. Thử gửi lại ngay khi đơn đang pending -> bị chặn
        res_dup = self.client.post(
            "/api/v1/absence-requests",
            json={
                "schedule_id": self.sched_today_id,
                "reason": "Em vẫn đang bị ốm xin gửi lại đơn.",
            },
            headers=headers,
        )
        self.assertEqual(res_dup.status_code, 400)
        self.assertEqual(res_dup.get_json()["code"], "DUPLICATE_PENDING_REQUEST")

        # 3. Giả lập đơn bị từ chối (rejected) trong cơ sở dữ liệu
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE absence_requests SET status = 'rejected', rejection_reason = 'Thiếu giấy khám bệnh' WHERE id = %s",
                    (request_id,),
                )
            conn.commit()
        finally:
            conn.close()

        # 4. Sau khi đơn cũ bị rejected -> được phép gửi lại đơn mới thành công!
        res_resubmit = self.client.post(
            "/api/v1/absence-requests",
            json={
                "schedule_id": self.sched_today_id,
                "reason": "Em xin gửi lại đơn kèm bổ sung thông tin theo yêu cầu thầy/cô.",
            },
            headers=headers,
        )
        self.assertEqual(res_resubmit.status_code, 201)
        new_data = res_resubmit.get_json()["data"]
        self.assertEqual(new_data["status"], "pending")
        self.assertNotEqual(new_data["id"], request_id)

    def test_06_list_my_absence_requests(self):
        """Học viên xem danh sách đơn của chính mình, phân trang và không thấy đơn của người khác."""
        headers_b = self._get_auth_header(self.student_b_user_id, "trainee")
        # Tạo thêm 1 đơn cho Học viên B trên Buổi Lớp B
        res_b = self.client.post(
            "/api/v1/absence-requests",
            json={
                "schedule_id": self.sched_class_b_id,
                "reason": "Em học viên B xin nghỉ phép.",
            },
            headers=headers_b,
        )
        self.assertEqual(res_b.status_code, 201)
        req_b_id = res_b.get_json()["data"]["id"]

        headers_a = self._get_auth_header(self.student_a_user_id, "trainee")
        # Học viên A truy vấn danh sách đơn của mình
        res = self.client.get(
            "/api/v1/absence-requests/my",
            headers=headers_a,
        )
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()["data"]
        items = json_data["items"]
        pagination = json_data["pagination"]

        # Học viên A thấy đơn của mình, không thấy đơn của học viên B
        my_request_ids = [item["id"] for item in items]
        self.assertNotIn(req_b_id, my_request_ids)
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(pagination["page"], 1)

    def test_07_get_absence_request_detail_and_access_control(self):
        """Kiểm tra quyền xem chi tiết đơn: Chủ đơn xem được (200), học viên khác bị chặn (403)."""
        headers_a = self._get_auth_header(self.student_a_user_id, "trainee")
        # Tạo đơn của Học viên A trên Buổi tương lai
        res = self.client.post(
            "/api/v1/absence-requests",
            json={
                "schedule_id": self.sched_future_id,
                "reason": "Em xin phép vắng buổi tới vì trùng lịch thi chứng chỉ.",
            },
            headers=headers_a,
        )
        self.assertEqual(res.status_code, 201)
        req_a_id = res.get_json()["data"]["id"]

        # 1. Học viên A xem chi tiết đơn của chính mình -> 200 OK
        res_owner = self.client.get(
            f"/api/v1/absence-requests/{req_a_id}",
            headers=headers_a,
        )
        self.assertEqual(res_owner.status_code, 200)
        detail = res_owner.get_json()["data"]
        self.assertEqual(detail["id"], req_a_id)
        self.assertEqual(detail["student_id"], self.student_a_id)
        self.assertEqual(detail["status"], "pending")

        # 2. Học viên B cố tình xem đơn của Học viên A -> 403 Forbidden
        headers_b = self._get_auth_header(self.student_b_user_id, "trainee")
        res_forbidden = self.client.get(
            f"/api/v1/absence-requests/{req_a_id}",
            headers=headers_b,
        )
        self.assertEqual(res_forbidden.status_code, 403)
        self.assertEqual(res_forbidden.get_json()["code"], "FORBIDDEN_ABSENCE_ACCESS")



if __name__ == "__main__":
    unittest.main()
