"""
Bộ kiểm thử tự động toàn diện cho SCRUM-256: BẢNG CHUYÊN CẦN TỔNG HỢP THEO LỚP.
Kiểm thử 3 tiêu chí nghiệm thu:
- AC1: Ma trận học viên theo buổi, ô màu theo trạng thái (bao gồm 2 buổi cùng ngày, phân quyền RBAC, học viên chưa điểm danh, tương lai, hủy, không áp dụng).
- AC2: Cột tổng số buổi vắng và tỷ lệ chuyên cần theo phần trăm (đối chiếu chính xác ví dụ mục 12: 3 vắng, 70%; D=0 ra None; tương lai/hủy không ảnh hưởng).
- AC3: Sắp xếp theo tỷ lệ chuyên cần tăng dần phía server (0% đứng đầu, null đứng cuối, tie-break ổn định theo student_code, phân trang không đổi tổng).
"""

from datetime import date, datetime, timedelta, time
import unittest
import uuid

from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.main import app
from app.services.attendance_service import VIETNAM_TZ


class Scrum256AttendanceSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = app.test_client()

        cls.suffix = uuid.uuid4().hex[:8]
        cls.tm_user_id = f"test-tm-{cls.suffix}"
        cls.admin_user_id = f"test-admin-{cls.suffix}"
        cls.trainer_assigned_id = f"test-tr-assigned-{cls.suffix}"
        cls.trainer_unassigned_id = f"test-tr-unassigned-{cls.suffix}"
        cls.trainee_user_id = f"test-trainee-{cls.suffix}"

        cls.program_id = f"prog-{cls.suffix}"
        cls.subject_id = f"subj-{cls.suffix}"
        cls.classroom_id = f"cr-{cls.suffix}"
        cls.class_id = f"cls-{cls.suffix}"
        cls.class_subject_id = f"cls-subj-{cls.suffix}"

        cls.past_date = date.today() - timedelta(days=5)
        cls.past_date_2 = date.today() - timedelta(days=4)
        cls.same_day_date = date.today() - timedelta(days=2)
        cls.future_date = date.today() + timedelta(days=5)

        # Tạo ID cho các buổi học
        cls.sched_past_1 = f"sched-p1-{cls.suffix}"
        cls.sched_past_2 = f"sched-p2-{cls.suffix}"
        cls.sched_same_day_morning = f"sched-sd-m-{cls.suffix}"
        cls.sched_same_day_afternoon = f"sched-sd-a-{cls.suffix}"
        cls.sched_cancelled = f"sched-canc-{cls.suffix}"
        cls.sched_future_1 = f"sched-f1-{cls.suffix}"
        cls.sched_future_2 = f"sched-f2-{cls.suffix}"

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Tạo users
                users = [
                    (cls.tm_user_id, f"tm_{cls.suffix}@ictu.edu.vn", "Training Manager"),
                    (cls.admin_user_id, f"admin_{cls.suffix}@ictu.edu.vn", "Pure Admin"),
                    (cls.trainer_assigned_id, f"tr_assigned_{cls.suffix}@ictu.edu.vn", "Assigned Trainer"),
                    (cls.trainer_unassigned_id, f"tr_unassigned_{cls.suffix}@ictu.edu.vn", "Unassigned Trainer"),
                    (cls.trainee_user_id, f"trainee_{cls.suffix}@ictu.edu.vn", "Trainee User"),
                ]
                for uid, email, name in users:
                    cur.execute(
                        "INSERT INTO users (id, email, password_hash, name, created_at, updated_at) "
                        "VALUES (%s, %s, 'hash', %s, NOW(), NOW())",
                        (uid, email, name),
                    )

                # 2. Gán roles
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-training-manager', NOW())", (cls.tm_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-admin', NOW())", (cls.admin_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.trainer_assigned_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.trainer_unassigned_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.trainee_user_id,))

                # 3. Training Program, Subject, Classroom
                cur.execute(
                    "INSERT INTO training_programs (id, code, name, description, status, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 'Test Program', 'active', NOW(), NOW())",
                    (cls.program_id, f"PRG_{cls.suffix}", f"Chương trình {cls.suffix}"),
                )
                cur.execute(
                    "INSERT INTO subjects (id, code, name, credits, status, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 3, 'active', NOW(), NOW())",
                    (cls.subject_id, f"SUB_{cls.suffix}", f"Môn học {cls.suffix}"),
                )
                cur.execute(
                    "INSERT INTO classrooms (id, room_code, room_name, capacity, room_type, status, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 40, 'standard', 'active', NOW(), NOW())",
                    (cls.classroom_id, f"P_{cls.suffix}", f"Phòng {cls.suffix}"),
                )

                # 4. Class & Class Subject
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, learning_mode, status, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, 30, 'offline', 'in_progress', NOW(), NOW())",
                    (cls.class_id, f"CLS_{cls.suffix}", cls.program_id, cls.past_date - timedelta(days=30)),
                )
                cur.execute(
                    "INSERT INTO class_subjects (id, class_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 1, 1, 1, NOW(), NOW())",
                    (cls.class_subject_id, cls.class_id, cls.subject_id),
                )

                # 5. Phân công trainer_assigned_id cho môn học của lớp
                cur.execute(
                    "INSERT INTO class_subject_instructors (id, class_subject_id, instructor_id, role_type, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 'main', NOW(), NOW())",
                    (f"csi-{cls.suffix}", cls.class_subject_id, cls.trainer_assigned_id),
                )

                # 6. Tạo các buổi học (bao gồm 2 buổi cùng ngày: sáng và chiều)
                schedules_data = [
                    (cls.sched_past_1, 1, "Buổi 1 Mở đầu", cls.past_date, "morning", "08:00:00", "10:30:00", "scheduled", 1),
                    (cls.sched_past_2, 2, "Buổi 2 Lý thuyết", cls.past_date_2, "morning", "08:00:00", "10:30:00", "scheduled", 1),
                    (cls.sched_same_day_morning, 3, "Buổi 3 Sáng", cls.same_day_date, "morning", "08:00:00", "10:30:00", "scheduled", 1),
                    (cls.sched_same_day_afternoon, 4, "Buổi 4 Chiều", cls.same_day_date, "afternoon", "13:30:00", "16:00:00", "scheduled", 0), # Chưa điểm danh
                    (cls.sched_cancelled, 5, "Buổi 5 Bão lụt", date.today() - timedelta(days=1), "morning", "08:00:00", "10:30:00", "cancelled", 0),
                    (cls.sched_future_1, 6, "Buổi 6 Thực hành", cls.future_date, "morning", "08:00:00", "10:30:00", "scheduled", 0),
                    (cls.sched_future_2, 7, "Buổi 7 Tổng kết", cls.future_date + timedelta(days=1), "morning", "08:00:00", "10:30:00", "scheduled", 0),
                ]

                for sid, snum, stopic, sdate, shift, stime, etime, status, att_checked in schedules_data:
                    cur.execute(
                        """
                        INSERT INTO class_schedules (
                            id, class_id, class_subject_id, subject_id, session_number,
                            topic, learning_date, shift, start_time, end_time, room_id,
                            instructor_id, status, attendance_checked, created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                        """,
                        (
                            sid, cls.class_id, cls.class_subject_id, cls.subject_id, snum,
                            stopic, sdate, shift, stime, etime, cls.classroom_id,
                            cls.trainer_assigned_id, status, att_checked,
                        ),
                    )

                conn.commit()
        finally:
            conn.close()

        cls.created_session_ids = []

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                if cls.created_session_ids:
                    fmt = ",".join(["%s"] * len(cls.created_session_ids))
                    cur.execute(f"DELETE FROM auth_sessions WHERE session_id IN ({fmt})", tuple(cls.created_session_ids))

                # Xóa dữ liệu điểm danh và buổi học
                cur.execute("DELETE FROM session_attendances WHERE schedule_id IN (%s, %s, %s, %s, %s, %s, %s)",
                            (cls.sched_past_1, cls.sched_past_2, cls.sched_same_day_morning, cls.sched_same_day_afternoon, cls.sched_cancelled, cls.sched_future_1, cls.sched_future_2))
                cur.execute("DELETE FROM class_schedules WHERE class_id = %s", (cls.class_id,))
                cur.execute("DELETE FROM class_subject_instructors WHERE class_subject_id = %s", (cls.class_subject_id,))
                cur.execute("DELETE FROM class_subjects WHERE class_id = %s", (cls.class_id,))
                cur.execute("DELETE FROM class_enrollments WHERE class_id = %s", (cls.class_id,))
                cur.execute("DELETE FROM classes WHERE id = %s", (cls.class_id,))
                cur.execute("DELETE FROM classrooms WHERE id = %s", (cls.classroom_id,))
                cur.execute("DELETE FROM subjects WHERE id = %s", (cls.subject_id,))
                cur.execute("DELETE FROM training_programs WHERE id = %s", (cls.program_id,))

                # Xóa test users
                cur.execute("DELETE FROM user_roles WHERE user_id IN (%s, %s, %s, %s, %s)",
                            (cls.tm_user_id, cls.admin_user_id, cls.trainer_assigned_id, cls.trainer_unassigned_id, cls.trainee_user_id))
                cur.execute("DELETE FROM users WHERE id IN (%s, %s, %s, %s, %s)",
                            (cls.tm_user_id, cls.admin_user_id, cls.trainer_assigned_id, cls.trainer_unassigned_id, cls.trainee_user_id))
                conn.commit()
        finally:
            conn.close()

    def _get_auth_header(self, user_id: str, role: str) -> dict[str, str]:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        self.__class__.created_session_ids.append(session_id)
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

    def _create_student_and_enrollment(self, student_code: str, full_name: str, enrolled_date: date = None, lifecycle_status: str = None, effective_date: date = None):
        """Helper tạo học viên và bản ghi ghi danh."""
        student_id = f"st-{uuid.uuid4().hex[:8]}"
        enrolled_dt = datetime.combine(enrolled_date or self.past_date - timedelta(days=20), time(8, 0))
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO students (id, student_code, full_name, email, phone, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, '0912345678', NOW(), NOW())",
                    (student_id, student_code, full_name, f"{student_code.lower()}@ictu.edu.vn"),
                )
                cur.execute(
                    """
                    INSERT INTO class_enrollments (
                        id, class_id, student_id, enrolled_at, status, lifecycle_status, effective_date, enrolled_by, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, 'enrolled', %s, %s, %s, NOW(), NOW())
                    """,
                    (f"enr-{uuid.uuid4().hex[:8]}", self.class_id, student_id, enrolled_dt, lifecycle_status, effective_date, self.tm_user_id),
                )
                conn.commit()
            return student_id
        finally:
            conn.close()

    def _record_attendance(self, schedule_id: str, student_id: str, status: str, notes: str = None):
        """Helper ghi nhận điểm danh."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO session_attendances (id, schedule_id, student_id, status, notes, recorded_by, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE status = VALUES(status), notes = VALUES(notes), updated_at = NOW()
                    """,
                    (f"att-{uuid.uuid4().hex[:8]}", schedule_id, student_id, status, notes, self.trainer_assigned_id),
                )
                conn.commit()
        finally:
            conn.close()

    # =========================================================================
    # AC1: MA TRẬN HỌC VIÊN THEO BUỔI & PHÂN QUYỀN
    # =========================================================================

    def test_ac1_rbac_assigned_trainer_can_access(self):
        """Giảng viên được phân công xem được bảng chuyên cần tổng hợp của lớp (200)."""
        res = self.client.get(
            f"/api/v1/classes/{self.class_id}/attendance-summary",
            headers=self._get_auth_header(self.trainer_assigned_id, "trainer"),
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["class_info"]["id"], self.class_id)
        self.assertIn("sessions", data)
        self.assertIn("students", data)

    def test_ac1_rbac_training_manager_can_access(self):
        """Quản lý đào tạo xem được mọi lớp học (200)."""
        res = self.client.get(
            f"/api/v1/classes/{self.class_id}/attendance-summary",
            headers=self._get_auth_header(self.tm_user_id, "training_manager"),
        )
        self.assertEqual(res.status_code, 200)

    def test_ac1_rbac_unassigned_trainer_forbidden(self):
        """Giảng viên KHÔNG được phân công cho lớp bị từ chối 403 (FORBIDDEN_ATTENDANCE_ACCESS)."""
        res = self.client.get(
            f"/api/v1/classes/{self.class_id}/attendance-summary",
            headers=self._get_auth_header(self.trainer_unassigned_id, "trainer"),
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN_ATTENDANCE_ACCESS")

    def test_ac1_rbac_trainee_and_admin_forbidden(self):
        """Học viên và admin thuần túy bị chặn truy cập 403."""
        for uid, role in ((self.trainee_user_id, "trainee"), (self.admin_user_id, "admin")):
            res = self.client.get(
                f"/api/v1/classes/{self.class_id}/attendance-summary",
                headers=self._get_auth_header(uid, role),
            )
            self.assertEqual(res.status_code, 403)

    def test_ac1_nonexistent_class_returns_404(self):
        """Lớp học không tồn tại trả về 404 (CLASS_NOT_FOUND)."""
        res = self.client.get(
            "/api/v1/classes/nonexistent-class-id/attendance-summary",
            headers=self._get_auth_header(self.tm_user_id, "training_manager"),
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "CLASS_NOT_FOUND")

    def test_ac1_same_day_sessions_are_separate_columns(self):
        """Hai buổi học trong cùng một ngày (sáng và chiều) là 2 cột riêng biệt trong ma trận."""
        res = self.client.get(
            f"/api/v1/classes/{self.class_id}/attendance-summary",
            headers=self._get_auth_header(self.tm_user_id, "training_manager"),
        )
        self.assertEqual(res.status_code, 200)
        sessions = res.get_json()["data"]["sessions"]
        same_day_cols = [s for s in sessions if s["learning_date"] == self.same_day_date.isoformat()]
        self.assertEqual(len(same_day_cols), 2)
        # Khác schedule_id và khác ca/giờ học
        self.assertNotEqual(same_day_cols[0]["schedule_id"], same_day_cols[1]["schedule_id"])
        self.assertEqual(same_day_cols[0]["shift"], "morning")
        self.assertEqual(same_day_cols[1]["shift"], "afternoon")

    def test_ac1_cell_statuses_and_colors(self):
        """Ma trận hiển thị đúng các ô màu, nhãn và ký hiệu cho từng trạng thái."""
        sid = self._create_student_and_enrollment(f"SV_AC1_{self.suffix}", "Học Viên AC1")
        # Ghi các trạng thái
        self._record_attendance(self.sched_past_1, sid, "present")
        self._record_attendance(self.sched_past_2, sid, "late")
        self._record_attendance(self.sched_same_day_morning, sid, "excused")
        # sched_same_day_afternoon: không ghi -> not_recorded
        # sched_cancelled: buổi hủy -> cancelled
        # sched_future_1: buổi tương lai -> future

        res = self.client.get(
            f"/api/v1/classes/{self.class_id}/attendance-summary?search={sid}",
            headers=self._get_auth_header(self.tm_user_id, "training_manager"),
        )
        self.assertEqual(res.status_code, 200)
        st_data = res.get_json()["data"]["students"][0]
        cells = st_data["session_statuses"]

        # Present
        self.assertEqual(cells[self.sched_past_1]["status"], "present")
        self.assertEqual(cells[self.sched_past_1]["color_token"], "green")
        self.assertEqual(cells[self.sched_past_1]["symbol"], "P")

        # Late
        self.assertEqual(cells[self.sched_past_2]["status"], "late")
        self.assertEqual(cells[self.sched_past_2]["color_token"], "orange")
        self.assertEqual(cells[self.sched_past_2]["symbol"], "L")

        # Excused
        self.assertEqual(cells[self.sched_same_day_morning]["status"], "excused")
        self.assertEqual(cells[self.sched_same_day_morning]["color_token"], "blue")
        self.assertEqual(cells[self.sched_same_day_morning]["symbol"], "E")

        # Not recorded (buổi kết thúc nhưng chưa điểm danh)
        self.assertEqual(cells[self.sched_same_day_afternoon]["status"], "not_recorded")
        self.assertEqual(cells[self.sched_same_day_afternoon]["color_token"], "grey")
        self.assertEqual(cells[self.sched_same_day_afternoon]["symbol"], "?")

        # Cancelled
        self.assertEqual(cells[self.sched_cancelled]["status"], "cancelled")
        self.assertEqual(cells[self.sched_cancelled]["symbol"], "✕")

        # Future
        self.assertEqual(cells[self.sched_future_1]["status"], "future")
        self.assertEqual(cells[self.sched_future_1]["symbol"], "—")

    def test_ac1_not_applicable_for_student_before_enrollment_or_after_drop(self):
        """Học viên nhập học sau ngày diễn ra buổi học hoặc đã thôi học trước ngày học -> Ô 'not_applicable'."""
        late_enrolled_date = self.past_date + timedelta(days=1)
        sid_late = self._create_student_and_enrollment(f"SV_LATE_{self.suffix}", "Học Viên Vào Muộn", enrolled_date=late_enrolled_date)

        res = self.client.get(
            f"/api/v1/classes/{self.class_id}/attendance-summary?search={sid_late}",
            headers=self._get_auth_header(self.tm_user_id, "training_manager"),
        )
        self.assertEqual(res.status_code, 200)
        st_data = res.get_json()["data"]["students"][0]
        cells = st_data["session_statuses"]

        # sched_past_1 diễn ra vào past_date, trước ngày late_enrolled_date
        self.assertEqual(cells[self.sched_past_1]["status"], "not_applicable")
        self.assertEqual(cells[self.sched_past_1]["symbol"], "—")
        self.assertFalse(cells[self.sched_past_1]["is_eligible"])

    # =========================================================================
    # AC2: CỘT TỔNG VẮNG VÀ TỶ LỆ CHUYÊN CẦN
    # =========================================================================

    def test_ac2_acceptance_criteria_exact_example(self):
        """
        Nghiệm thu chính xác ví dụ Mục 12 trong bản đặc tả SCRUM-256:
        Học viên có:
        - 6 buổi Có mặt.
        - 1 buổi Đi muộn.
        - 1 buổi Vắng có phép.
        - 2 buổi Vắng không phép.
        - 1 buổi đã kết thúc nhưng Chưa điểm danh.
        - 2 buổi tương lai.

        Kết quả kỳ vọng:
        - Tổng vắng = 3 (1 có phép + 2 không phép).
        - Mẫu số D = 10 (6 có mặt + 1 đi muộn + 1 có phép + 2 không phép).
        - Tỷ lệ = 70.0% ((6 + 1) / 10 * 100%).
        - Buổi đã kết thúc chưa điểm danh = 1.
        - Hai buổi tương lai KHÔNG ảnh hưởng các tổng trên.
        """
        sid = self._create_student_and_enrollment(f"SV_EX12_{self.suffix}", "Học Viên Mục 12")

        # Tạo thêm các buổi học trong quá khứ để khớp đúng số lượng ví dụ 12 (tổng 10 buổi quá khứ có kết quả + 1 chưa điểm danh + 2 tương lai)
        extra_schedules = []
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                for i in range(1, 8):
                    sched_id = f"sched-extra-{i}-{self.suffix}"
                    extra_schedules.append(sched_id)
                    cur.execute(
                        """
                        INSERT INTO class_schedules (
                            id, class_id, class_subject_id, subject_id, session_number,
                            topic, learning_date, shift, start_time, end_time, room_id,
                            instructor_id, status, attendance_checked, created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, 'Extra Past Session', %s, 'morning', '08:00:00', '10:30:00', %s, %s, 'scheduled', 1, NOW(), NOW())
                        """,
                        (sched_id, self.class_id, self.class_subject_id, self.subject_id, 10 + i, self.past_date - timedelta(days=i + 5), self.classroom_id, self.trainer_assigned_id),
                    )
                conn.commit()
        finally:
            conn.close()

        # Tổng cộng các buổi:
        # sched_past_1: Có mặt (1)
        # sched_past_2: Có mặt (2)
        # sched_same_day_morning: Có mặt (3)
        # extra 1: Có mặt (4)
        # extra 2: Có mặt (5)
        # extra 3: Có mặt (6)
        # extra 4: Đi muộn (1)
        # extra 5: Vắng có phép (1)
        # extra 6: Vắng không phép (1)
        # extra 7: Vắng không phép (2)
        # sched_same_day_afternoon: chưa điểm danh (1)
        # sched_future_1 & sched_future_2: tương lai (2)
        self._record_attendance(self.sched_past_1, sid, "present")
        self._record_attendance(self.sched_past_2, sid, "present")
        self._record_attendance(self.sched_same_day_morning, sid, "present")
        self._record_attendance(extra_schedules[0], sid, "present")
        self._record_attendance(extra_schedules[1], sid, "present")
        self._record_attendance(extra_schedules[2], sid, "present")
        self._record_attendance(extra_schedules[3], sid, "late")
        self._record_attendance(extra_schedules[4], sid, "excused")
        self._record_attendance(extra_schedules[5], sid, "unexcused")
        self._record_attendance(extra_schedules[6], sid, "unexcused")

        # Đồng thời tạo trước 1 đơn xin nghỉ (excused) cho buổi tương lai sched_future_1 để kiểm tra
        # rằng buổi tương lai được duyệt nghỉ KHÔNG bị cộng vào tổng vắng hoặc mẫu số
        self._record_attendance(self.sched_future_1, sid, "excused", notes="Nghỉ có phép duyệt trước")

        res = self.client.get(
            f"/api/v1/classes/{self.class_id}/attendance-summary?search={sid}",
            headers=self._get_auth_header(self.tm_user_id, "training_manager"),
        )
        self.assertEqual(res.status_code, 200)
        st_data = res.get_json()["data"]["students"][0]
        summary = st_data["summary"]

        self.assertEqual(summary["present_count"], 6)
        self.assertEqual(summary["late_count"], 1)
        self.assertEqual(summary["excused_count"], 1)
        self.assertEqual(summary["unexcused_count"], 2)
        self.assertEqual(summary["attended_count"], 7)
        self.assertEqual(summary["total_absent"], 3)
        self.assertEqual(summary["valid_sessions_count"], 10)
        self.assertEqual(summary["attendance_rate"], 70.0)
        self.assertEqual(summary["unrecorded_ended_count"], 1)

        # Kiểm tra cell tương lai có cờ is_pre_approved
        cell_future = st_data["session_statuses"][self.sched_future_1]
        self.assertEqual(cell_future["status"], "excused")
        self.assertTrue(cell_future.get("is_pre_approved"))

    def test_ac2_zero_denominator_returns_null(self):
        """Học viên chưa có buổi học nào có kết quả điểm danh -> D = 0 -> Tỷ lệ là null (hiển thị '—')."""
        sid = self._create_student_and_enrollment(f"SV_NO_ATT_{self.suffix}", "Học Viên Chưa Có Điểm Danh")

        res = self.client.get(
            f"/api/v1/classes/{self.class_id}/attendance-summary?search={sid}",
            headers=self._get_auth_header(self.tm_user_id, "training_manager"),
        )
        self.assertEqual(res.status_code, 200)
        st_data = res.get_json()["data"]["students"][0]
        summary = st_data["summary"]

        self.assertEqual(summary["valid_sessions_count"], 0)
        self.assertEqual(summary["total_absent"], 0)
        self.assertIsNone(summary["attendance_rate"])

    # =========================================================================
    # AC3: SẮP XẾP TỶ LỆ CHUYÊN CẦN TĂNG DẦN
    # =========================================================================

    def test_ac3_server_side_sorting_rate_asc(self):
        """
        Nghiệm thu tiêu chí sắp xếp AC3:
        Tập dữ liệu:
        - A: 0%
        - B: 50%
        - C: 70%
        - D: 100%
        - E: null (chưa có dữ liệu)
        - F: 50%

        Kỳ vọng thứ tự sắp xếp tăng dần:
        A (0%) -> B, F (50% ổn định theo student_code) -> C (70%) -> D (100%) -> E (null đặt cuối cùng).
        """
        # Tạo 1 lớp cô lập riêng để kiểm thử chính xác thứ tự sort
        test_class_id = f"cls-sort-{self.suffix}"
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, max_capacity, status, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 30, 'in_progress', NOW(), NOW())",
                    (test_class_id, f"CLS_SORT_{self.suffix}", self.program_id),
                )
                cur.execute(
                    "INSERT INTO class_subjects (id, class_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 1, 1, 1, NOW(), NOW())",
                    (f"cs-sort-{self.suffix}", test_class_id, self.subject_id),
                )

                # Tạo 2 buổi học trong quá khứ
                s1 = f"s-sort-1-{self.suffix}"
                s2 = f"s-sort-2-{self.suffix}"
                cur.execute(
                    "INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, room_id, instructor_id, status, attendance_checked, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 1, 'Sort Session 1', %s, 'morning', '08:00:00', '10:30:00', %s, %s, 'scheduled', 1, NOW(), NOW())",
                    (s1, test_class_id, self.subject_id, self.past_date, self.classroom_id, self.trainer_assigned_id),
                )
                cur.execute(
                    "INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, room_id, instructor_id, status, attendance_checked, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 2, 'Sort Session 2', %s, 'morning', '08:00:00', '10:30:00', %s, %s, 'scheduled', 1, NOW(), NOW())",
                    (s2, test_class_id, self.subject_id, self.past_date_2, self.classroom_id, self.trainer_assigned_id),
                )

                # Tạo 6 học viên A, B, C, D, E, F
                students_setup = [
                    ("A", "SV_A", "unexcused", "unexcused"), # 0/2 = 0%
                    ("B", "SV_B", "present", "unexcused"),   # 1/2 = 50%
                    ("F", "SV_F", "late", "excused"),        # 1/2 = 50%
                    ("D", "SV_D", "present", "present"),     # 2/2 = 100%
                    ("E", "SV_E", None, None),               # 0/0 = None
                ]

                created_map = {}
                for tag, code, st1, st2 in students_setup:
                    sid = f"st-sort-{tag}-{self.suffix}"
                    created_map[tag] = sid
                    cur.execute(
                        "INSERT INTO students (id, student_code, full_name, email, phone, created_at, updated_at) "
                        "VALUES (%s, %s, %s, %s, '0987654321', NOW(), NOW())",
                        (sid, code, f"Student {tag}", f"{code.lower()}@ictu.edu.vn"),
                    )
                    cur.execute(
                        "INSERT INTO class_enrollments (id, class_id, student_id, enrolled_at, status, enrolled_by, created_at, updated_at) "
                        "VALUES (%s, %s, %s, %s, 'enrolled', %s, NOW(), NOW())",
                        (f"enr-sort-{tag}-{self.suffix}", test_class_id, sid, self.past_date - timedelta(days=10), self.tm_user_id),
                    )
                    if st1:
                        cur.execute(
                            "INSERT INTO session_attendances (id, schedule_id, student_id, status, created_at, updated_at) VALUES (%s, %s, %s, %s, NOW(), NOW())",
                            (f"att-{tag}-1-{self.suffix}", s1, sid, st1),
                        )
                    if st2:
                        cur.execute(
                            "INSERT INTO session_attendances (id, schedule_id, student_id, status, created_at, updated_at) VALUES (%s, %s, %s, %s, NOW(), NOW())",
                            (f"att-{tag}-2-{self.suffix}", s2, sid, st2),
                        )

                conn.commit()

            # Gọi API với sort_by=attendance_rate&sort_order=asc
            res = self.client.get(
                f"/api/v1/classes/{test_class_id}/attendance-summary?sort_by=attendance_rate&sort_order=asc",
                headers=self._get_auth_header(self.tm_user_id, "training_manager"),
            )
            self.assertEqual(res.status_code, 200)
            students = res.get_json()["data"]["students"]
            codes = [s["student_code"] for s in students]

            # Kiểm tra thứ tự chính xác:
            # A: 0% -> đầu tiên
            self.assertEqual(codes[0], "SV_A")
            self.assertEqual(students[0]["summary"]["attendance_rate"], 0.0)

            # B và F: 50% -> tiếp theo, B đứng trước F theo mã học viên
            self.assertEqual(codes[1], "SV_B")
            self.assertEqual(students[1]["summary"]["attendance_rate"], 50.0)

            self.assertEqual(codes[2], "SV_F")
            self.assertEqual(students[2]["summary"]["attendance_rate"], 50.0)

            # D: 100% -> tiếp theo
            self.assertEqual(codes[3], "SV_D")
            self.assertEqual(students[3]["summary"]["attendance_rate"], 100.0)

            # E: null -> cuối cùng
            self.assertEqual(codes[4], "SV_E")
            self.assertIsNone(students[4]["summary"]["attendance_rate"])

        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM session_attendances WHERE schedule_id IN (SELECT id FROM class_schedules WHERE class_id = %s)", (test_class_id,))
                cur.execute("DELETE FROM class_schedules WHERE class_id = %s", (test_class_id,))
                cur.execute("DELETE FROM class_subjects WHERE class_id = %s", (test_class_id,))
                cur.execute("DELETE FROM class_enrollments WHERE class_id = %s", (test_class_id,))
                cur.execute("DELETE FROM classes WHERE id = %s", (test_class_id,))
                cur.execute("DELETE FROM students WHERE id LIKE %s", (f"st-sort-%-{self.suffix}",))
                conn.commit()
            conn.close()

    def test_ac3_server_side_pagination_and_search(self):
        """Phân trang và tìm kiếm: total_items phản ánh đúng số lượng tìm kiếm, phân trang không làm lệch tổng số."""
        res = self.client.get(
            f"/api/v1/classes/{self.class_id}/attendance-summary?page=1&page_size=2",
            headers=self._get_auth_header(self.tm_user_id, "training_manager"),
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        pagination = data["pagination"]
        self.assertEqual(pagination["page"], 1)
        self.assertEqual(pagination["page_size"], 2)
        self.assertGreaterEqual(pagination["total_items"], 2)
        self.assertEqual(len(data["students"]), 2)


if __name__ == "__main__":
    unittest.main()
