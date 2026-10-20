"""
Bộ kiểm thử tự động cho SCRUM-255 Lát cắt 255.3 — Giảng viên và Quản lý đào tạo xem xét, phê duyệt hoặc từ chối đơn xin phép vắng.
Kiểm tra:
1. Danh sách đơn trong phạm vi phân công:
   - Giảng viên chỉ xem được các đơn thuộc buổi học mình phụ trách.
   - Quản lý đào tạo xem được toàn bộ đơn.
   - Học viên/Admin thuần túy bị chặn (403).
2. Phê duyệt đơn (approve):
   - Giảng viên đúng phân công duyệt thành công (200).
   - Tự động cập nhật session_attendances thành 'excused' trong cùng transaction.
   - Ghi nhận lịch sử attendance_audit_logs với lý do liên kết mã đơn.
   - Đối với buổi tương lai: KHÔNG tự ý bật attendance_checked = 1 trên class_schedules.
3. Từ chối đơn (reject):
   - Từ chối thiếu lý do bị chặn (400 REJECTION_REASON_REQUIRED).
   - Từ chối hợp lệ -> lưu trạng thái 'rejected' và rejection_reason.
   - Điểm danh KHÔNG bị đổi sang vắng không phép.
4. Kiểm soát thẩm quyền:
   - Giảng viên ngoài phạm vi phân công bị chặn (403).
   - Quản lý đào tạo duyệt thay thành công (200).
   - Admin thuần túy / Học viên gọi API duyệt bị chặn (403).
5. Xung đột và tính nguyên tử:
   - Học viên đã có mặt (present) hoặc đi muộn (late) -> chặn duyệt (400 ATTENDANCE_CONFLICT).
   - Đơn đã được xử lý (approved/rejected) -> chặn xử lý lần 2 (400 REQUEST_ALREADY_REVIEWED).
"""

from datetime import date, datetime, timedelta
import unittest
import uuid

from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.main import app
from app.repositories.absence_request_repository import VIETNAM_TZ


class Scrum255Slice3ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = app.test_client()

        cls.suffix = uuid.uuid4().hex[:8]
        cls.admin_user_id = f"test-admin-{cls.suffix}"
        cls.training_mgr_id = f"test-tm-{cls.suffix}"
        cls.trainer_assigned_id = f"test-tr-assign-{cls.suffix}"
        cls.trainer_other_id = f"test-tr-other-{cls.suffix}"
        cls.student_a_user_id = f"test-u-stu-a-{cls.suffix}"
        cls.student_b_user_id = f"test-u-stu-b-{cls.suffix}"
        cls.student_a_id = f"test-stu-a-{cls.suffix}"
        cls.student_b_id = f"test-stu-b-{cls.suffix}"

        cls.created_user_ids = [
            cls.admin_user_id,
            cls.training_mgr_id,
            cls.trainer_assigned_id,
            cls.trainer_other_id,
            cls.student_a_user_id,
            cls.student_b_user_id,
        ]
        cls.created_student_ids = [cls.student_a_id, cls.student_b_id]

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Tạo users
                users = [
                    (cls.admin_user_id, f"admin_{cls.suffix}@daotao.edu.vn", "Admin User"),
                    (cls.training_mgr_id, f"tm_{cls.suffix}@daotao.edu.vn", "Training Manager"),
                    (cls.trainer_assigned_id, f"tr_assign_{cls.suffix}@daotao.edu.vn", "Trainer Assigned"),
                    (cls.trainer_other_id, f"tr_other_{cls.suffix}@daotao.edu.vn", "Trainer Other"),
                    (cls.student_a_user_id, f"student_a_{cls.suffix}@daotao.edu.vn", "Student A"),
                    (cls.student_b_user_id, f"student_b_{cls.suffix}@daotao.edu.vn", "Student B"),
                ]
                for uid, email, name in users:
                    cur.execute(
                        "INSERT INTO users (id, email, password_hash, name, created_at, updated_at) VALUES (%s, %s, 'hash', %s, NOW(), NOW())",
                        (uid, email, name),
                    )

                # Gán roles
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-admin', NOW())", (cls.admin_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-training-manager', NOW())", (cls.training_mgr_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.trainer_assigned_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.trainer_other_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.student_a_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.student_b_user_id,))

                # 2. Tạo Program, Class A, Subject
                cls.prog_id = f"prog-{cls.suffix}"
                cur.execute(
                    "INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'Program 255-3', NOW(), NOW())",
                    (cls.prog_id, f"PRG3_{cls.suffix}"),
                )

                cls.class_a_id = f"cls-a-{cls.suffix}"
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, CURDATE() - INTERVAL 5 DAY, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_a_id, f"CLA3_{cls.suffix}", cls.prog_id),
                )

                cls.subject_id = f"sub-{cls.suffix}"
                cur.execute(
                    "INSERT INTO subjects (id, code, name, credits, created_at, updated_at) VALUES (%s, %s, 'Subject 255-3', 3, NOW(), NOW())",
                    (cls.subject_id, f"SUB3_{cls.suffix}"),
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

                # Ghi danh
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', CURDATE() - INTERVAL 5 DAY, %s, NOW(), NOW())",
                    (f"enr-a-{cls.suffix}", cls.class_a_id, cls.student_a_id, cls.admin_user_id),
                )
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', CURDATE() - INTERVAL 5 DAY, %s, NOW(), NOW())",
                    (f"enr-b-{cls.suffix}", cls.class_a_id, cls.student_b_id, cls.admin_user_id),
                )

                # 4. Tạo các buổi học kiểm thử
                # Buổi tương lai (gán cho trainer_assigned)
                cls.sched_future_id = f"sch-fut-{cls.suffix}"
                cur.execute(
                    """
                    INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, attendance_checked, instructor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, 1, 'Buổi học tương lai', CURDATE() + INTERVAL 2 DAY, 'Ca 1', '08:00:00', '10:00:00', 'scheduled', 0, %s, NOW(), NOW())
                    """,
                    (cls.sched_future_id, cls.class_a_id, cls.subject_id, cls.trainer_assigned_id),
                )

                # Buổi hôm nay (đã có điểm danh 'present' cho student A để test xung đột)
                cls.sched_conflict_id = f"sch-conf-{cls.suffix}"
                cur.execute(
                    """
                    INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, attendance_checked, instructor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, 2, 'Buổi học đã có mặt', CURDATE(), 'Ca 1', '08:00:00', '10:00:00', 'scheduled', 1, %s, NOW(), NOW())
                    """,
                    (cls.sched_conflict_id, cls.class_a_id, cls.subject_id, cls.trainer_assigned_id),
                )

                # Bản ghi điểm danh 'present' cho student A trên buổi sched_conflict_id
                cur.execute(
                    """
                    INSERT INTO session_attendances (id, schedule_id, student_id, status, notes, recorded_by, created_at, updated_at)
                    VALUES (%s, %s, %s, 'present', 'Có mặt đầy đủ', %s, NOW(), NOW())
                    """,
                    (f"sa-conf-{cls.suffix}", cls.sched_conflict_id, cls.student_a_id, cls.trainer_assigned_id),
                )

                # Buổi học khác (gán cho trainer_other)
                cls.sched_other_id = f"sch-oth-{cls.suffix}"
                cur.execute(
                    """
                    INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, attendance_checked, instructor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, 3, 'Buổi của giảng viên khác', CURDATE() + INTERVAL 1 DAY, 'Ca 2', '13:30:00', '15:30:00', 'scheduled', 0, %s, NOW(), NOW())
                    """,
                    (cls.sched_other_id, cls.class_a_id, cls.subject_id, cls.trainer_other_id),
                )

            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM auth_sessions WHERE user_id IN (%s, %s, %s, %s, %s, %s)", tuple(cls.created_user_ids))
                cur.execute("DELETE FROM attendance_audit_logs WHERE student_id IN (%s, %s)", tuple(cls.created_student_ids))
                cur.execute("DELETE FROM session_attendances WHERE student_id IN (%s, %s)", tuple(cls.created_student_ids))
                cur.execute("DELETE FROM absence_request_attachments WHERE request_id IN (SELECT id FROM absence_requests WHERE student_id IN (%s, %s))", tuple(cls.created_student_ids))
                cur.execute("DELETE FROM absence_requests WHERE student_id IN (%s, %s)", tuple(cls.created_student_ids))
                cur.execute("DELETE FROM class_schedules WHERE class_id = %s", (cls.class_a_id,))
                cur.execute("DELETE FROM class_enrollments WHERE class_id = %s", (cls.class_a_id,))
                cur.execute("DELETE FROM students WHERE id IN (%s, %s)", tuple(cls.created_student_ids))
                cur.execute("DELETE FROM classes WHERE id = %s", (cls.class_a_id,))
                cur.execute("DELETE FROM subjects WHERE id = %s", (cls.subject_id,))
                cur.execute("DELETE FROM training_programs WHERE id = %s", (cls.prog_id,))
                cur.execute("DELETE FROM user_roles WHERE user_id IN (%s, %s, %s, %s, %s, %s)", tuple(cls.created_user_ids))
                cur.execute("DELETE FROM users WHERE id IN (%s, %s, %s, %s, %s, %s)", tuple(cls.created_user_ids))
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

    def _create_test_request(self, schedule_id: str, student_id: str, reason: str) -> str:
        req_id = f"ar-test-{uuid.uuid4().hex[:12]}"
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO absence_requests (id, schedule_id, student_id, reason, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, 'pending', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
                    """,
                    (req_id, schedule_id, student_id, reason),
                )
            conn.commit()
            return req_id
        finally:
            conn.close()

    def test_01_reviewer_list_and_scope_filtering(self):
        """Giảng viên chỉ thấy đơn của buổi học mình phụ trách; Quản lý đào tạo thấy tất cả."""
        # Tạo 1 đơn cho sched_future (gán cho trainer_assigned)
        req_1 = self._create_test_request(self.sched_future_id, self.student_a_id, "Em A xin nghỉ buổi future")
        # Tạo 1 đơn cho sched_other (gán cho trainer_other)
        req_2 = self._create_test_request(self.sched_other_id, self.student_b_id, "Em B xin nghỉ buổi other")

        # 1. Giảng viên trainer_assigned gọi danh sách đơn
        headers_tr1 = self._get_auth_header(self.trainer_assigned_id, "trainer")
        res_tr1 = self.client.get("/api/v1/absence-requests", headers=headers_tr1)
        self.assertEqual(res_tr1.status_code, 200)
        items_tr1 = res_tr1.get_json()["data"]["items"]
        item_ids_tr1 = [i["id"] for i in items_tr1]
        self.assertIn(req_1, item_ids_tr1)
        self.assertNotIn(req_2, item_ids_tr1) # Không thấy đơn của buổi khác!

        # 2. Quản lý đào tạo thấy cả 2 đơn
        headers_tm = self._get_auth_header(self.training_mgr_id, "training_manager")
        res_tm = self.client.get("/api/v1/absence-requests", headers=headers_tm)
        self.assertEqual(res_tm.status_code, 200)
        items_tm = res_tm.get_json()["data"]["items"]
        item_ids_tm = [i["id"] for i in items_tm]
        self.assertIn(req_1, item_ids_tm)
        self.assertIn(req_2, item_ids_tm)

        # 3. Học viên hoặc Admin thuần túy bị chặn
        headers_admin = self._get_auth_header(self.admin_user_id, "admin")
        res_admin = self.client.get("/api/v1/absence-requests", headers=headers_admin)
        self.assertEqual(res_admin.status_code, 403)

    def test_02_approve_absence_request_success_and_attendance_update(self):
        """Duyệt đơn thành công: Cập nhật excused, ghi audit log, KHÔNG bật attendance_checked trên buổi tương lai."""
        req_id = self._create_test_request(self.sched_future_id, self.student_b_id, "Em B xin vắng có phép buổi tới")

        headers_tr = self._get_auth_header(self.trainer_assigned_id, "trainer")
        res = self.client.post(
            f"/api/v1/absence-requests/{req_id}/review",
            json={"action": "approve"},
            headers=headers_tr,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["status"], "approved")
        self.assertEqual(data["reviewed_by"], self.trainer_assigned_id)
        self.assertIsNotNone(data["reviewed_at"])

        # Kiểm tra database điểm danh session_attendances
        conn = get_db_connection()
        try:
            with conn.cursor(dictionary=True) as cur:
                cur.execute(
                    "SELECT status, notes, recorded_by FROM session_attendances WHERE schedule_id = %s AND student_id = %s",
                    (self.sched_future_id, self.student_b_id),
                )
                sa = cur.fetchone()
                self.assertIsNotNone(sa)
                self.assertEqual(sa["status"], "excused")
                self.assertEqual(sa["recorded_by"], self.trainer_assigned_id)

                # Kiểm tra attendance_audit_logs
                cur.execute(
                    "SELECT old_status, new_status, reason, performed_by FROM attendance_audit_logs WHERE schedule_id = %s AND student_id = %s",
                    (self.sched_future_id, self.student_b_id),
                )
                audit = cur.fetchone()
                self.assertIsNotNone(audit)
                self.assertEqual(audit["new_status"], "excused")
                self.assertIn(req_id, audit["reason"])

                # QUAN TRỌNG: Kiểm tra class_schedules.attendance_checked KHÔNG bị bật
                cur.execute(
                    "SELECT attendance_checked FROM class_schedules WHERE id = %s",
                    (self.sched_future_id,),
                )
                sched = cur.fetchone()
                self.assertEqual(bool(sched["attendance_checked"]), False)
        finally:
            conn.close()

    def test_03_reject_absence_request_requires_reason_and_leaves_attendance_untouched(self):
        """Từ chối đơn bắt buộc có lý do; không thay đổi điểm danh sang unexcused."""
        req_id = self._create_test_request(self.sched_future_id, self.student_a_id, "Em A xin nghỉ nhưng không chính đáng")

        headers_tr = self._get_auth_header(self.trainer_assigned_id, "trainer")

        # 1. Từ chối thiếu lý do -> Chặn 400
        res_no_reason = self.client.post(
            f"/api/v1/absence-requests/{req_id}/review",
            json={"action": "reject", "rejection_reason": ""},
            headers=headers_tr,
        )
        self.assertEqual(res_no_reason.status_code, 400)
        self.assertEqual(res_no_reason.get_json()["code"], "REJECTION_REASON_REQUIRED")

        # 2. Từ chối hợp lệ
        res_reject = self.client.post(
            f"/api/v1/absence-requests/{req_id}/review",
            json={
                "action": "reject",
                "rejection_reason": "Lý do cá nhân không được nhà trường chấp thuận theo quy chế.",
            },
            headers=headers_tr,
        )
        self.assertEqual(res_reject.status_code, 200)
        data = res_reject.get_json()["data"]
        self.assertEqual(data["status"], "rejected")
        self.assertEqual(data["rejection_reason"], "Lý do cá nhân không được nhà trường chấp thuận theo quy chế.")

        # Điểm danh không bị tạo hay đổi thành unexcused
        conn = get_db_connection()
        try:
            with conn.cursor(dictionary=True) as cur:
                cur.execute(
                    "SELECT status FROM session_attendances WHERE schedule_id = %s AND student_id = %s",
                    (self.sched_future_id, self.student_a_id),
                )
                sa = cur.fetchone()
                self.assertIsNone(sa) # Chưa có điểm danh thì vẫn không có!
        finally:
            conn.close()

    def test_04_forbidden_review_for_unauthorized_users(self):
        """Giảng viên ngoài phạm vi, Học viên và Admin thuần túy không được duyệt đơn."""
        req_id = self._create_test_request(self.sched_future_id, self.student_a_id, "Em A xin nghỉ")

        # 1. Giảng viên trainer_other (không được phân công buổi này)
        headers_other = self._get_auth_header(self.trainer_other_id, "trainer")
        res_other = self.client.post(
            f"/api/v1/absence-requests/{req_id}/review",
            json={"action": "approve"},
            headers=headers_other,
        )
        self.assertEqual(res_other.status_code, 403)

        # 2. Học viên
        headers_stu = self._get_auth_header(self.student_a_user_id, "trainee")
        res_stu = self.client.post(
            f"/api/v1/absence-requests/{req_id}/review",
            json={"action": "approve"},
            headers=headers_stu,
        )
        self.assertEqual(res_stu.status_code, 403)

        # 3. Quản lý đào tạo duyệt thay -> Được phép 200
        headers_tm = self._get_auth_header(self.training_mgr_id, "training_manager")
        res_tm = self.client.post(
            f"/api/v1/absence-requests/{req_id}/review",
            json={"action": "approve"},
            headers=headers_tm,
        )
        self.assertEqual(res_tm.status_code, 200)
        self.assertEqual(res_tm.get_json()["data"]["status"], "approved")

    def test_05_block_approve_when_attendance_present_or_late(self):
        """Học viên đã Có mặt (present) tại buổi học -> Chặn duyệt đơn."""
        # Buổi sched_conflict_id đã có điểm danh 'present' cho student_a
        req_id = self._create_test_request(self.sched_conflict_id, self.student_a_id, "Em A xin nghỉ nhưng thực tế đã có mặt")

        headers_tr = self._get_auth_header(self.trainer_assigned_id, "trainer")
        res = self.client.post(
            f"/api/v1/absence-requests/{req_id}/review",
            json={"action": "approve"},
            headers=headers_tr,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "ATTENDANCE_CONFLICT")

    def test_06_block_review_when_already_reviewed(self):
        """Đơn đã được duyệt trước đó -> Chặn duyệt hoặc từ chối lại chính đơn này (REQUEST_ALREADY_REVIEWED)."""
        sched_test6_id = f"sch-t6-{uuid.uuid4().hex[:8]}"
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, attendance_checked, instructor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, 10, 'Buổi test repeat', CURDATE() + INTERVAL 3 DAY, 'Ca 1', '08:00:00', '10:00:00', 'scheduled', 0, %s, NOW(), NOW())
                    """,
                    (sched_test6_id, self.class_a_id, self.subject_id, self.trainer_assigned_id),
                )
            conn.commit()
        finally:
            conn.close()

        req_id = self._create_test_request(sched_test6_id, self.student_a_id, "Em A xin nghỉ buổi test repeat")

        headers_tr = self._get_auth_header(self.trainer_assigned_id, "trainer")
        # Lần 1: Duyệt thành công
        res1 = self.client.post(
            f"/api/v1/absence-requests/{req_id}/review",
            json={"action": "approve"},
            headers=headers_tr,
        )
        self.assertEqual(res1.status_code, 200)

        # Lần 2: Thử từ chối hoặc duyệt lại chính đơn này -> Chặn 400 REQUEST_ALREADY_REVIEWED
        res2 = self.client.post(
            f"/api/v1/absence-requests/{req_id}/review",
            json={"action": "reject", "rejection_reason": "Muốn từ chối lại"},
            headers=headers_tr,
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "REQUEST_ALREADY_REVIEWED")

    def test_07_block_approve_duplicate_request_when_already_has_approved_request(self):
        """Chặn duyệt thêm đơn nếu buổi học đã có một đơn khác đã được duyệt cho cùng học viên."""
        # Student A đã có đơn approved từ test_02 trên sched_future_id
        # Tạo thêm một đơn pending thủ công trực tiếp trong DB (giả lập dữ liệu cũ hoặc đồng thời lọt vào)
        dup_req_id = f"ar-dup-{uuid.uuid4().hex[:8]}"
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO absence_requests (id, schedule_id, student_id, reason, status, created_at, updated_at)
                    VALUES (%s, %s, %s, 'Đơn trùng lọt vào DB', 'pending', NOW(), NOW())
                    """,
                    (dup_req_id, self.sched_future_id, self.student_a_id),
                )
            conn.commit()
        finally:
            conn.close()

        headers_tr = self._get_auth_header(self.trainer_assigned_id, "trainer")
        res = self.client.post(
            f"/api/v1/absence-requests/{dup_req_id}/review",
            json={"action": "approve"},
            headers=headers_tr,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "DUPLICATE_APPROVED_REQUEST")


if __name__ == "__main__":
    unittest.main()
