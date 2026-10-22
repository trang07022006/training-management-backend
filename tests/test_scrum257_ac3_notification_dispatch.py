"""
Targeted tests for SCRUM-257 - Acceptance Criteria 3 (AC3):
Thông báo cho Giảng viên và Quản lý đào tạo khi cờ cảnh báo vắng được bật.

Bao quát:
1. Bật cờ tạo đúng thông báo cho giảng viên phụ trách lớp và quản lý đào tạo.
2. Không gửi cho người ngoài phạm vi (giảng viên lớp khác, học viên).
3. Không gửi trùng khi một người có nhiều vai trò (vừa giảng viên vừa quản lý: chỉ 1 thông báo).
4. Cờ vẫn bật và job chạy lại không phát thêm thông báo (chống trùng theo đợt).
5. Tắt rồi bật lại tạo đúng một thông báo cho mỗi người nhận ở đợt mới (alert_round tăng).
6. Ràng buộc UNIQUE (alert_id, alert_round, recipient_id) bảo vệ chống trùng khi chạy đồng thời.
7. Nội dung thông báo đúng quy chuẩn: "Học viên ... có tỷ lệ vắng X%, vượt ngưỡng Y% của lớp ...".
8. Endpoint GET /api/v1/absence-alerts/notifications/my: Trả về thông báo của đúng người nhận.
9. Endpoint POST /api/v1/absence-alerts/notifications/<id>/read: Đánh dấu đã đọc, bảo vệ quyền người nhận.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch
import uuid
from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.database.ensure_business_roles import ensure_business_roles
from app.main import app
from app.models.login_session import LoginSession
from app.models.training_program import TrainingProgram
from app.repositories import (
    absence_alert_repository,
    training_program_repository,
)
from app.services import absence_alert_service


class Scrum257AC3NotificationDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_business_roles()

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.today = self.now.date()
        self.conn = get_db_connection()
        self.cursor = self.conn.cursor(dictionary=True)

        self.sessions = {}

        def side_effect_get_session(sid):
            uid = self.sessions.get(sid)
            if not uid:
                return None
            return LoginSession(
                session_id=sid,
                user_id=uid,
                refresh_jti=f"ref-{sid}",
                created_at=self.now,
                last_activity_at=self.now,
                idle_expires_at=self.now + timedelta(hours=8),
                absolute_expires_at=self.now + timedelta(hours=8),
            )

        self.session_patcher = patch(
            "app.utils.rbac_auth.get_session_by_id",
            side_effect=side_effect_get_session,
        )
        self.mock_get_session = self.session_patcher.start()

        self.created_notification_ids = []
        self.created_alert_ids = []
        self.created_attendances = []
        self.created_schedules = []
        self.created_enrollments = []
        self.created_class_subject_instructors = []
        self.created_class_subjects = []
        self.created_classes = []
        self.created_subjects = []
        self.created_students = []
        self.created_programs = []
        self.created_users = []

    def tearDown(self):
        self.session_patcher.stop()

        try:
            if self.created_notification_ids:
                fmt = ",".join(["%s"] * len(self.created_notification_ids))
                self.cursor.execute(f"DELETE FROM absence_alert_notifications WHERE id IN ({fmt})", tuple(self.created_notification_ids))

            if self.created_alert_ids:
                fmt = ",".join(["%s"] * len(self.created_alert_ids))
                self.cursor.execute(f"DELETE FROM absence_alert_notifications WHERE alert_id IN ({fmt})", tuple(self.created_alert_ids))
                self.cursor.execute(f"DELETE FROM student_absence_alerts WHERE id IN ({fmt})", tuple(self.created_alert_ids))

            if self.created_attendances:
                fmt = ",".join(["%s"] * len(self.created_attendances))
                self.cursor.execute(f"DELETE FROM session_attendances WHERE id IN ({fmt})", tuple(self.created_attendances))

            if self.created_schedules:
                fmt = ",".join(["%s"] * len(self.created_schedules))
                self.cursor.execute(f"DELETE FROM session_attendances WHERE schedule_id IN ({fmt})", tuple(self.created_schedules))
                self.cursor.execute(f"DELETE FROM class_schedules WHERE id IN ({fmt})", tuple(self.created_schedules))

            if self.created_enrollments:
                fmt = ",".join(["%s"] * len(self.created_enrollments))
                self.cursor.execute(f"DELETE FROM class_enrollments WHERE id IN ({fmt})", tuple(self.created_enrollments))

            if self.created_class_subject_instructors:
                fmt = ",".join(["%s"] * len(self.created_class_subject_instructors))
                self.cursor.execute(f"DELETE FROM class_subject_instructors WHERE id IN ({fmt})", tuple(self.created_class_subject_instructors))

            if self.created_class_subjects:
                fmt = ",".join(["%s"] * len(self.created_class_subjects))
                self.cursor.execute(f"DELETE FROM class_subjects WHERE id IN ({fmt})", tuple(self.created_class_subjects))

            if self.created_classes:
                fmt = ",".join(["%s"] * len(self.created_classes))
                self.cursor.execute(f"DELETE FROM student_absence_alerts WHERE class_id IN ({fmt})", tuple(self.created_classes))
                self.cursor.execute(f"DELETE FROM classes WHERE id IN ({fmt})", tuple(self.created_classes))

            if self.created_subjects:
                fmt = ",".join(["%s"] * len(self.created_subjects))
                self.cursor.execute(f"DELETE FROM subjects WHERE id IN ({fmt})", tuple(self.created_subjects))

            if self.created_students:
                fmt = ",".join(["%s"] * len(self.created_students))
                self.cursor.execute(f"DELETE FROM student_absence_alerts WHERE student_id IN ({fmt})", tuple(self.created_students))
                self.cursor.execute(f"DELETE FROM class_enrollments WHERE student_id IN ({fmt})", tuple(self.created_students))
                self.cursor.execute(f"DELETE FROM students WHERE id IN ({fmt})", tuple(self.created_students))

            if self.created_programs:
                fmt = ",".join(["%s"] * len(self.created_programs))
                self.cursor.execute(f"DELETE FROM training_programs WHERE id IN ({fmt})", tuple(self.created_programs))

            if self.created_users:
                fmt = ",".join(["%s"] * len(self.created_users))
                self.cursor.execute(f"DELETE FROM absence_alert_notifications WHERE recipient_id IN ({fmt})", tuple(self.created_users))
                self.cursor.execute(f"DELETE FROM user_roles WHERE user_id IN ({fmt})", tuple(self.created_users))
                self.cursor.execute(f"DELETE FROM users WHERE id IN ({fmt})", tuple(self.created_users))

            self.conn.commit()
        except Exception:
            self.conn.rollback()
        finally:
            self.cursor.close()
            self.conn.close()

    def _insert_user(self, user_id: str, email: str, role: str, name: str):
        self.cursor.execute(
            """
            INSERT INTO users (id, email, password_hash, role, status, name, failed_login_attempts, created_at, updated_at)
            VALUES (%s, %s, 'hash', %s, 'active', %s, 0, NOW(), NOW())
            ON DUPLICATE KEY UPDATE role = VALUES(role), name = VALUES(name)
            """,
            (user_id, email, role, name),
        )
        role_id_map = {
            "training_manager": "role-id-training-manager",
            "trainer": "role-id-trainer",
            "trainee": "role-id-trainee",
        }
        role_id = role_id_map.get(role, "role-id-user")
        self.cursor.execute(
            "INSERT IGNORE INTO user_roles (user_id, role_id, created_at) VALUES (%s, %s, NOW())",
            (user_id, role_id),
        )
        self.conn.commit()
        self.created_users.append(user_id)

    def _assign_role(self, user_id: str, role: str):
        role_id_map = {
            "training_manager": "role-id-training-manager",
            "trainer": "role-id-trainer",
            "trainee": "role-id-trainee",
        }
        role_id = role_id_map.get(role, "role-id-user")
        self.cursor.execute(
            "INSERT IGNORE INTO user_roles (user_id, role_id, created_at) VALUES (%s, %s, NOW())",
            (user_id, role_id),
        )
        self.conn.commit()

    def _create_token(self, user_id: str, roles: list[str]) -> str:
        sid = f"sid-{uuid.uuid4()}"
        self.sessions[sid] = user_id
        with self.app.app_context():
            return create_access_token(
                identity=user_id,
                additional_claims={"roles": roles, "sid": sid},
            )

    def _create_program(self, code, name, threshold=20.0):
        prog_id = str(uuid.uuid4())
        p = TrainingProgram(
            id=prog_id,
            code=code,
            name=name,
            duration_semesters=4,
            status="active",
            standard_tuition_fee=12000000,
            absence_alert_threshold=threshold,
            created_at=self.now,
            updated_at=self.now,
        )
        training_program_repository.insert_training_program(p)
        self.created_programs.append(prog_id)
        return prog_id

    def _create_class(self, program_id, code):
        class_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO classes (id, class_code, program_id, max_capacity, learning_mode, status, created_at, updated_at)
            VALUES (%s, %s, %s, 30, 'offline', 'active', %s, %s)
            """,
            (class_id, code, program_id, self.now, self.now),
        )
        self.conn.commit()
        self.created_classes.append(class_id)
        return class_id

    def _create_subject(self, code, name):
        sub_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO subjects (id, code, name, credits, total_sessions, status, created_at, updated_at)
            VALUES (%s, %s, %s, 3, 20, 'active', %s, %s)
            """,
            (sub_id, code, name, self.now, self.now),
        )
        self.conn.commit()
        self.created_subjects.append(sub_id)
        return sub_id

    def _create_class_subject_with_instructor(self, class_id, subject_id, instructor_id):
        cs_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO class_subjects (id, class_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at)
            VALUES (%s, %s, %s, 1, 1, 1, %s, %s)
            """,
            (cs_id, class_id, subject_id, self.now, self.now),
        )
        self.created_class_subjects.append(cs_id)

        csi_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO class_subject_instructors (id, class_subject_id, instructor_id, role_type, created_at, updated_at)
            VALUES (%s, %s, %s, 'main', %s, %s)
            """,
            (csi_id, cs_id, instructor_id, self.now, self.now),
        )
        self.conn.commit()
        self.created_class_subject_instructors.append(csi_id)
        return cs_id

    def _create_student(self, user_id, code, name, email):
        stu_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO students (id, student_code, user_id, full_name, phone, email, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, '0988776655', %s, 'enrolled', %s, %s)
            """,
            (stu_id, code, user_id, name, email, self.now, self.now),
        )
        self.conn.commit()
        self.created_students.append(stu_id)
        return stu_id

    def _enroll_student(self, class_id, student_id, manager_id):
        enr_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO class_enrollments (id, class_id, student_id, enrolled_by, enrolled_at, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 'enrolled', %s, %s)
            """,
            (enr_id, class_id, student_id, manager_id, self.now - timedelta(days=30), self.now, self.now),
        )
        self.conn.commit()
        self.created_enrollments.append(enr_id)
        return enr_id

    def _create_schedules(self, class_id: str, subject_id: str, total_count: int, past_count: int) -> list[str]:
        sched_ids = []
        for i in range(total_count):
            sid = str(uuid.uuid4())
            sched_ids.append(sid)
            self.created_schedules.append(sid)

            if i < past_count:
                ld = self.today - timedelta(days=(past_count - i))
                checked = 1
            else:
                ld = self.today + timedelta(days=(i - past_count + 1))
                checked = 0

            self.cursor.execute(
                """
                INSERT INTO class_schedules (
                    id, class_id, subject_id, session_number, topic, learning_date,
                    shift, start_time, end_time, status, attendance_checked, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, 1, '08:00:00', '10:00:00', 'scheduled', %s, %s, %s)
                """,
                (sid, class_id, subject_id, i + 1, f"Bài học {i + 1}", ld, checked, self.now, self.now),
            )
        self.conn.commit()
        return sched_ids

    def _record_attendance(self, schedule_id, student_id, status):
        att_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO session_attendances (id, schedule_id, student_id, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE status = VALUES(status), updated_at = VALUES(updated_at)
            """,
            (att_id, schedule_id, student_id, status, self.now, self.now),
        )
        self.conn.commit()
        self.created_attendances.append(att_id)
        return att_id

    def test_notification_dispatched_to_trainer_and_manager_when_flag_turns_on(self):
        """AC3: Bật cờ tạo đúng thông báo cho giảng viên phụ trách và quản lý đào tạo."""
        suffix = uuid.uuid4().hex[:6]
        trainer_user_id = str(uuid.uuid4())
        manager_user_id = str(uuid.uuid4())
        other_trainer_user_id = str(uuid.uuid4())
        student_user_id = str(uuid.uuid4())

        self._insert_user(trainer_user_id, f"trn_{suffix}@ictu.test", "trainer", f"Giảng Viên Phụ Trách {suffix}")
        self._insert_user(manager_user_id, f"mgr_{suffix}@ictu.test", "training_manager", f"Quản Lý Đào Tạo {suffix}")
        self._insert_user(other_trainer_user_id, f"othertrn_{suffix}@ictu.test", "trainer", f"Giảng Viên Khác {suffix}")
        self._insert_user(student_user_id, f"stu_{suffix}@ictu.test", "trainee", f"Học Viên Vắng {suffix}")

        program_id = self._create_program(f"PRG-{suffix}", f"Chương Trình {suffix}", 20.0)
        class_id = self._create_class(program_id, f"CLS-{suffix}")
        subject_id = self._create_subject(f"SUB-{suffix}", f"Môn Học {suffix}")
        self._create_class_subject_with_instructor(class_id, subject_id, trainer_user_id)

        student_id = self._create_student(student_user_id, f"HV{suffix.upper()}", f"Học Viên Vắng {suffix}", f"stu_{suffix}@ictu.test")
        self._enroll_student(class_id, student_id, manager_user_id)

        # 20 buổi học, 15 buổi đã qua, 5 buổi vắng: 5/20 = 25% > 20%
        schedules = self._create_schedules(class_id, subject_id, total_count=20, past_count=15)
        for i in range(5):
            self._record_attendance(schedules[i], student_id, "unexcused")
        for i in range(5, 15):
            self._record_attendance(schedules[i], student_id, "present")

        results = absence_alert_service.evaluate_class_absence_alerts(class_id=class_id, persist=True)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["is_flagged"])
        self.assertEqual(results[0]["status"], "active")

        # Kiểm tra bảng absence_alert_notifications
        self.cursor.execute(
            """
            SELECT * FROM absence_alert_notifications
            WHERE alert_id = %s
            ORDER BY created_at ASC
            """,
            (results[0]["alert_id"],),
        )
        notifs = self.cursor.fetchall()
        self.assertGreaterEqual(len(notifs), 2, "Phải gửi cho Giảng viên phụ trách và Quản lý đào tạo")

        recipient_ids = {n["recipient_id"] for n in notifs}
        self.assertIn(trainer_user_id, recipient_ids, "Giảng viên phụ trách lớp phải nhận được thông báo")
        self.assertIn(manager_user_id, recipient_ids, "Quản lý đào tạo phải nhận được thông báo")
        self.assertNotIn(other_trainer_user_id, recipient_ids, "Giảng viên ngoài lớp KHÔNG được nhận thông báo")
        self.assertNotIn(student_user_id, recipient_ids, "Học viên KHÔNG nhận thông báo trong AC3")

        # Kiểm tra nội dung thông báo
        for n in notifs:
            self.assertIn("vắng vượt ngưỡng", n["title"].lower())
            self.assertIn("25%", n["message"])
            self.assertIn("vượt ngưỡng 20%", n["message"])
            self.assertFalse(n["is_read"])
            self.assertEqual(n["alert_round"], 1)

    def test_multi_role_user_deduplication(self):
        """AC3: Người có nhiều vai trò (vừa giảng viên phụ trách vừa quản lý) chỉ nhận 1 thông báo."""
        suffix = uuid.uuid4().hex[:6]
        multi_user_id = str(uuid.uuid4())
        student_user_id = str(uuid.uuid4())

        self._insert_user(multi_user_id, f"multi_{suffix}@ictu.test", "trainer", f"Thầy Quản Lý {suffix}")
        self._assign_role(multi_user_id, "training_manager")
        self._insert_user(student_user_id, f"stu_{suffix}@ictu.test", "trainee", f"Học Viên Multi {suffix}")

        program_id = self._create_program(f"PRG-{suffix}", f"Chương Trình {suffix}", 20.0)
        class_id = self._create_class(program_id, f"CLS-{suffix}")
        subject_id = self._create_subject(f"SUB-{suffix}", f"Môn Học {suffix}")
        self._create_class_subject_with_instructor(class_id, subject_id, multi_user_id)

        student_id = self._create_student(student_user_id, f"HV{suffix.upper()}", f"Học Viên Multi {suffix}", f"stu_{suffix}@ictu.test")
        self._enroll_student(class_id, student_id, multi_user_id)

        # 10 buổi học, 6 buổi qua, 3 vắng (3/10 = 30% > 20%)
        schedules = self._create_schedules(class_id, subject_id, total_count=10, past_count=6)
        for i in range(3):
            self._record_attendance(schedules[i], student_id, "unexcused")
        for i in range(3, 6):
            self._record_attendance(schedules[i], student_id, "present")

        results = absence_alert_service.evaluate_class_absence_alerts(class_id=class_id, persist=True)
        self.assertTrue(results[0]["is_flagged"])

        self.cursor.execute(
            "SELECT * FROM absence_alert_notifications WHERE alert_id = %s AND recipient_id = %s",
            (results[0]["alert_id"], multi_user_id),
        )
        notifs = self.cursor.fetchall()
        self.assertEqual(len(notifs), 1, "Người có nhiều vai trò chỉ được nhận đúng 1 thông báo cho cùng sự kiện")

    def test_no_duplicate_notifications_on_subsequent_runs_while_flag_remains_active(self):
        """AC3: Cờ vẫn bật và job chạy lại / evaluate lại KHÔNG phát thêm thông báo trùng."""
        suffix = uuid.uuid4().hex[:6]
        trainer_user_id = str(uuid.uuid4())
        student_user_id = str(uuid.uuid4())

        self._insert_user(trainer_user_id, f"dedup_trn_{suffix}@ictu.test", "trainer", f"Giảng Viên Chống Trùng {suffix}")
        self._insert_user(student_user_id, f"dedup_stu_{suffix}@ictu.test", "trainee", f"Học Viên Chống Trùng {suffix}")

        program_id = self._create_program(f"PRG-{suffix}", f"Chương Trình {suffix}", 20.0)
        class_id = self._create_class(program_id, f"CLS-{suffix}")
        subject_id = self._create_subject(f"SUB-{suffix}", f"Môn Dedup {suffix}")
        self._create_class_subject_with_instructor(class_id, subject_id, trainer_user_id)

        student_id = self._create_student(student_user_id, f"HV{suffix.upper()}", f"Học Viên Dedup {suffix}", f"dedup_stu_{suffix}@ictu.test")
        self._enroll_student(class_id, student_id, trainer_user_id)

        # 10 buổi, 6 buổi qua, 3 vắng (30% > 20%)
        schedules = self._create_schedules(class_id, subject_id, total_count=10, past_count=6)
        for i in range(3):
            self._record_attendance(schedules[i], student_id, "unexcused")
        for i in range(3, 6):
            self._record_attendance(schedules[i], student_id, "present")

        # Lần chạy 1: cờ bật -> thông báo phát đi
        results1 = absence_alert_service.evaluate_class_absence_alerts(class_id=class_id, persist=True)
        self.assertTrue(results1[0]["is_flagged"])

        self.cursor.execute(
            "SELECT COUNT(*) AS c FROM absence_alert_notifications WHERE alert_id = %s",
            (results1[0]["alert_id"],),
        )
        count_first = self.cursor.fetchone()["c"]
        self.assertGreaterEqual(count_first, 1)

        # Lần chạy 2 (job lặp lại): cờ vẫn bật -> không phát thêm
        results2 = absence_alert_service.evaluate_class_absence_alerts(class_id=class_id, persist=True)
        self.cursor.execute(
            "SELECT COUNT(*) AS c FROM absence_alert_notifications WHERE alert_id = %s",
            (results1[0]["alert_id"],),
        )
        count_second = self.cursor.fetchone()["c"]
        self.assertEqual(count_first, count_second, "Job chạy lại không được phát thêm thông báo trùng")

        # Thêm 1 buổi vắng nữa (4/10 = 40%), cờ vẫn bật -> không gửi lại thông báo
        self._record_attendance(schedules[3], student_id, "unexcused")
        results3 = absence_alert_service.evaluate_class_absence_alerts(class_id=class_id, persist=True)
        self.cursor.execute(
            "SELECT COUNT(*) AS c FROM absence_alert_notifications WHERE alert_id = %s",
            (results1[0]["alert_id"],),
        )
        count_third = self.cursor.fetchone()["c"]
        self.assertEqual(count_first, count_third, "Tỷ lệ tăng thêm nhưng cờ vẫn đang bật không gửi lại thông báo")

    def test_notification_for_new_round_after_flag_resolves_and_re_triggers(self):
        """AC3: Cờ tắt rồi vượt lại tạo đúng một thông báo cho đợt mới (alert_round = 2)."""
        suffix = uuid.uuid4().hex[:6]
        trainer_user_id = str(uuid.uuid4())
        student_user_id = str(uuid.uuid4())

        self._insert_user(trainer_user_id, f"ret_trn_{suffix}@ictu.test", "trainer", f"Giảng Viên ReTrigger {suffix}")
        self._insert_user(student_user_id, f"ret_stu_{suffix}@ictu.test", "trainee", f"Học Viên ReTrigger {suffix}")

        program_id = self._create_program(f"PRG-{suffix}", f"Chương Trình {suffix}", 20.0)
        class_id = self._create_class(program_id, f"CLS-{suffix}")
        subject_id = self._create_subject(f"SUB-{suffix}", f"Môn ReTrigger {suffix}")
        self._create_class_subject_with_instructor(class_id, subject_id, trainer_user_id)

        student_id = self._create_student(student_user_id, f"HV{suffix.upper()}", f"Học Viên ReTrigger {suffix}", f"ret_stu_{suffix}@ictu.test")
        self._enroll_student(class_id, student_id, trainer_user_id)

        # 20 buổi: 5 vắng ban đầu (25% > 20%) -> Bật cờ đợt 1
        schedules = self._create_schedules(class_id, subject_id, total_count=20, past_count=15)
        for i in range(5):
            self._record_attendance(schedules[i], student_id, "unexcused")
        for i in range(5, 15):
            self._record_attendance(schedules[i], student_id, "present")

        r1 = absence_alert_service.evaluate_class_absence_alerts(class_id=class_id, persist=True)
        self.assertTrue(r1[0]["is_flagged"])
        self.assertEqual(r1[0]["status"], "active")

        # Sửa buổi 5 thành present: 4/20 = 20% <= 20% -> Tắt cờ
        self._record_attendance(schedules[4], student_id, "present")
        r2 = absence_alert_service.evaluate_class_absence_alerts(class_id=class_id, persist=True)
        self.assertFalse(r2[0]["is_flagged"])
        self.assertEqual(r2[0]["status"], "inactive")

        # Sửa lại buổi 5 thành unexcused: 5/20 = 25% > 20% -> Bật lại cờ đợt 2!
        self._record_attendance(schedules[4], student_id, "unexcused")
        r3 = absence_alert_service.evaluate_class_absence_alerts(class_id=class_id, persist=True)
        self.assertTrue(r3[0]["is_flagged"])
        self.assertEqual(r3[0]["status"], "active")

        # Kiểm tra thông báo của trainer: phải có đợt 1 và đợt 2
        self.cursor.execute(
            """
            SELECT alert_round, title, message FROM absence_alert_notifications
            WHERE alert_id = %s AND recipient_id = %s
            ORDER BY alert_round ASC
            """,
            (r3[0]["alert_id"], trainer_user_id),
        )
        notifs = self.cursor.fetchall()
        self.assertEqual(len(notifs), 2, "Phải có đúng 2 thông báo tương ứng 2 đợt cảnh báo khác nhau")
        self.assertEqual(notifs[0]["alert_round"], 1)
        self.assertEqual(notifs[1]["alert_round"], 2)

    def test_unique_constraint_concurrency_protection(self):
        """AC3: Unique constraint (alert_id, alert_round, recipient_id) ngăn chặn duplicate dưới race condition."""
        suffix = uuid.uuid4().hex[:6]
        trainer_user_id = str(uuid.uuid4())
        student_user_id = str(uuid.uuid4())

        self._insert_user(trainer_user_id, f"uniq_trn_{suffix}@ictu.test", "trainer", f"GV Unique {suffix}")
        self._insert_user(student_user_id, f"uniq_stu_{suffix}@ictu.test", "trainee", f"HV Unique {suffix}")

        program_id = self._create_program(f"PRG-{suffix}", f"Chương Trình {suffix}", 20.0)
        class_id = self._create_class(program_id, f"CLS-{suffix}")
        student_id = self._create_student(student_user_id, f"HV{suffix.upper()}", f"HV Unique {suffix}", f"uniq_stu_{suffix}@ictu.test")

        saved_alert = absence_alert_repository.upsert_student_absence_alert(
            class_id=class_id,
            student_id=student_id,
            program_id=program_id,
            status="active",
            absent_sessions=5,
            total_sessions=20,
            absence_rate=25.00,
            threshold=20.00,
        )
        alert_id = saved_alert["id"]
        self.created_alert_ids.append(alert_id)

        # Lần chèn 1: thành công
        notif1_id = str(uuid.uuid4())
        inserted1 = absence_alert_repository.insert_absence_alert_notification({
            "id": notif1_id,
            "alert_id": alert_id,
            "alert_round": 1,
            "recipient_id": trainer_user_id,
            "recipient_role": "trainer",
            "title": "Cảnh báo vắng đợt 1",
            "message": "Test message 1",
            "class_id": class_id,
            "student_id": student_id,
        })
        self.assertTrue(inserted1)
        self.created_notification_ids.append(notif1_id)

        # Lần chèn 2 đồng thời (cùng alert_id, alert_round, recipient_id): INSERT IGNORE trả về False, không crash
        notif2_id = str(uuid.uuid4())
        inserted2 = absence_alert_repository.insert_absence_alert_notification({
            "id": notif2_id,
            "alert_id": alert_id,
            "alert_round": 1,
            "recipient_id": trainer_user_id,
            "recipient_role": "trainer",
            "title": "Cảnh báo vắng đợt 1 duplicate",
            "message": "Test message 1 duplicate",
            "class_id": class_id,
            "student_id": student_id,
        })
        self.assertFalse(inserted2, "Lần chèn thứ 2 cho cùng đợt và người nhận phải bị bỏ qua (idempotent)")

    def test_api_my_notifications_and_mark_as_read(self):
        """AC3: Endpoint GET /api/v1/absence-alerts/notifications/my và POST /api/v1/absence-alerts/notifications/<id>/read."""
        suffix = uuid.uuid4().hex[:6]
        trainer_user_id = str(uuid.uuid4())
        other_user_id = str(uuid.uuid4())
        student_user_id = str(uuid.uuid4())

        self._insert_user(trainer_user_id, f"api_trn_{suffix}@ictu.test", "trainer", f"Giảng Viên API {suffix}")
        self._insert_user(other_user_id, f"api_oth_{suffix}@ictu.test", "trainee", f"Người Dùng Khác {suffix}")
        self._insert_user(student_user_id, f"api_stu_{suffix}@ictu.test", "trainee", f"Học Viên API {suffix}")

        program_id = self._create_program(f"PRG-{suffix}", f"Chương Trình {suffix}", 20.0)
        class_id = self._create_class(program_id, f"CLS-{suffix}")
        student_id = self._create_student(student_user_id, f"HV{suffix.upper()}", f"Học Viên API {suffix}", f"api_stu_{suffix}@ictu.test")

        saved_alert = absence_alert_repository.upsert_student_absence_alert(
            class_id=class_id,
            student_id=student_id,
            program_id=program_id,
            status="active",
            absent_sessions=5,
            total_sessions=20,
            absence_rate=25.00,
            threshold=20.00,
        )
        alert_id = saved_alert["id"]
        self.created_alert_ids.append(alert_id)
        self.conn.commit()

        notif_id = str(uuid.uuid4())
        absence_alert_repository.insert_absence_alert_notification({
            "id": notif_id,
            "alert_id": alert_id,
            "alert_round": 1,
            "recipient_id": trainer_user_id,
            "recipient_role": "trainer",
            "title": "Học viên vắng vượt ngưỡng",
            "message": "Học viên có tỷ lệ vắng 25%, vượt ngưỡng 20%",
            "class_id": class_id,
            "student_id": student_id,
        })
        self.created_notification_ids.append(notif_id)

        # 1. Chưa đăng nhập -> 401
        res = self.client.get("/api/v1/absence-alerts/notifications/my")
        self.assertEqual(res.status_code, 401)

        # 2. Đăng nhập với trainer_user_id -> Nhận được thông báo
        token_trainer = self._create_token(trainer_user_id, ["trainer"])
        headers = {"Authorization": f"Bearer {token_trainer}"}
        res = self.client.get("/api/v1/absence-alerts/notifications/my", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], notif_id)
        self.assertFalse(data[0]["is_read"])

        # 3. User khác đăng nhập -> Không thấy thông báo của trainer
        token_other = self._create_token(other_user_id, ["trainee"])
        headers_other = {"Authorization": f"Bearer {token_other}"}
        res_other = self.client.get("/api/v1/absence-alerts/notifications/my", headers=headers_other)
        self.assertEqual(res_other.status_code, 200)
        self.assertEqual(len(res_other.get_json()["data"]), 0)

        # 4. User khác cố đánh dấu đã đọc thông báo của trainer -> 404/Forbidden
        res_hack = self.client.post(
            f"/api/v1/absence-alerts/notifications/{notif_id}/read",
            headers=headers_other,
        )
        self.assertEqual(res_hack.status_code, 404)

        # 5. Chính trainer đánh dấu đã đọc -> 200 Thành công
        res_read = self.client.post(
            f"/api/v1/absence-alerts/notifications/{notif_id}/read",
            headers=headers,
        )
        self.assertEqual(res_read.status_code, 200)
        self.assertEqual(res_read.get_json()["code"], "NOTIFICATION_MARKED_READ")

        # 6. Kiểm tra lại với query unread_only=true -> rỗng
        res_unread = self.client.get(
            "/api/v1/absence-alerts/notifications/my?unread_only=true",
            headers=headers,
        )
        self.assertEqual(res_unread.status_code, 200)
        self.assertEqual(len(res_unread.get_json()["data"]), 0)


if __name__ == "__main__":
    unittest.main()
