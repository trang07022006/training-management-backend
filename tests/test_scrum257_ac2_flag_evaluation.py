"""
Targeted tests for SCRUM-257 - Acceptance Criteria 2 (AC2):
Gắn cờ cảnh báo học viên vắng vượt ngưỡng trên danh sách lớp và hồ sơ học viên.

Bao quát:
1. 4/20 buổi tại ngưỡng 20%: Chưa vượt ngưỡng (20% <= 20%), KHÔNG bật cờ.
2. 5/20 buổi tại ngưỡng 20%: Vượt ngưỡng (25% > 20%), BẬT cờ (status='active').
3. Sửa điểm danh giảm vắng về 4/20: Cờ TẮT (status='inactive', resolved_at được ghi nhận).
4. Vượt lại lên 5/20: Cờ BẬT lại, alert_round tăng lên 2 (vòng cảnh báo mới).
5. Một học viên học 2 lớp: Cảnh báo độc lập, lớp này vượt không làm bật cờ lớp kia.
6. N = 0 (lớp chưa xếp lịch hoặc không có buổi hợp lệ): Không chia cho 0, không bật cờ, insufficient_data = True.
7. Buổi tương lai: Không tính vào A.
8. Buổi bị hủy: Loại khỏi cả A và N.
9. Buổi chưa điểm danh (unrecorded): Không tự suy diễn thành vắng, không tính vào A.
10. Vắng có phép (excused) và Vắng không phép (unexcused): Đều được tính vào A.
11. Tích hợp API GET /api/v1/classes/<id>/attendance-summary: Trả về absence_alert cho từng học viên.
12. Tích hợp API GET /api/v1/students/<id>/absence-alerts: Trả về các cảnh báo đang bật trên hồ sơ học viên.
"""

from datetime import date, datetime, timedelta, timezone
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


class Scrum257AC2FlagEvaluationTests(unittest.TestCase):
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

        self.session_patcher = patch("app.utils.rbac_auth.get_session_by_id", side_effect=side_effect_get_session)
        self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)

        suffix = uuid.uuid4().hex[:6]
        self.manager_user_id = str(uuid.uuid4())
        self.trainer_user_id = str(uuid.uuid4())
        self.student_user_id = str(uuid.uuid4())

        self._insert_user(self.manager_user_id, f"mgr_{suffix}@ictu.test", "training_manager", "Quản Lý Đào Tạo")
        self._insert_user(self.trainer_user_id, f"trn_{suffix}@ictu.test", "trainer", "Giảng Viên Chính")
        self._insert_user(self.student_user_id, f"stu_{suffix}@ictu.test", "trainee", "Học Viên Test")

        # Student record
        self.student_id = str(uuid.uuid4())
        self.student_code = f"HV{suffix.upper()}"
        self.cursor.execute(
            """
            INSERT INTO students (id, student_code, user_id, full_name, phone, email, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, '0988776655', %s, 'enrolled', %s, %s)
            """,
            (self.student_id, self.student_code, self.student_user_id, "Học Viên Test", f"stu_{suffix}@ictu.test", self.now, self.now),
        )

        # Training program với ngưỡng 20.0%
        self.program_id = str(uuid.uuid4())
        p = TrainingProgram(
            id=self.program_id,
            code=f"PRG-{suffix}",
            name="Chương Trình Đào Tạo AC2",
            duration_semesters=4,
            status="active",
            standard_tuition_fee=12000000,
            absence_alert_threshold=20.0,
            created_at=self.now,
            updated_at=self.now,
        )
        training_program_repository.insert_training_program(p)

        # Subject
        self.subject_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO subjects (id, code, name, credits, total_sessions, status, created_at, updated_at)
            VALUES (%s, %s, %s, 3, 20, 'active', %s, %s)
            """,
            (self.subject_id, f"SUB-{suffix}", "Lập trình Web nâng cao", self.now, self.now),
        )

        # Class 1
        self.class1_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO classes (id, class_code, program_id, max_capacity, learning_mode, status, created_at, updated_at)
            VALUES (%s, %s, %s, 30, 'offline', 'active', %s, %s)
            """,
            (self.class1_id, f"CLS1-{suffix}", self.program_id, self.now, self.now),
        )

        # Class 2 (dành cho kiểm tra độc lập giữa các lớp)
        self.class2_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO classes (id, class_code, program_id, max_capacity, learning_mode, status, created_at, updated_at)
            VALUES (%s, %s, %s, 30, 'offline', 'active', %s, %s)
            """,
            (self.class2_id, f"CLS2-{suffix}", self.program_id, self.now, self.now),
        )

        # Ghi danh học viên vào cả Class 1 và Class 2
        self.cursor.execute(
            """
            INSERT INTO class_enrollments (id, class_id, student_id, enrolled_by, enrolled_at, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 'enrolled', %s, %s),
                   (%s, %s, %s, %s, %s, 'enrolled', %s, %s)
            """,
            (
                str(uuid.uuid4()), self.class1_id, self.student_id, self.manager_user_id, self.now - timedelta(days=30), self.now, self.now,
                str(uuid.uuid4()), self.class2_id, self.student_id, self.manager_user_id, self.now - timedelta(days=30), self.now, self.now,
            ),
        )

        # Phân công giảng viên vào Class 1
        cs1_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO class_subjects (id, class_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at)
            VALUES (%s, %s, %s, 1, 1, 1, %s, %s)
            """,
            (cs1_id, self.class1_id, self.subject_id, self.now, self.now),
        )
        self.cursor.execute(
            """
            INSERT INTO class_subject_instructors (id, class_subject_id, instructor_id, role_type, created_at, updated_at)
            VALUES (%s, %s, %s, 'main', %s, %s)
            """,
            (str(uuid.uuid4()), cs1_id, self.trainer_user_id, self.now, self.now),
        )
        self.conn.commit()

        # Tokens
        self.manager_token = self._create_token(self.manager_user_id, ["training_manager"])
        self.trainer_token = self._create_token(self.trainer_user_id, ["trainer"])

        # Lưu danh sách schedules tạo ra để dọn dẹp
        self.created_schedules = []

    def tearDown(self):
        try:
            if self.created_schedules:
                fmt = ",".join(["%s"] * len(self.created_schedules))
                self.cursor.execute(f"DELETE FROM session_attendances WHERE schedule_id IN ({fmt})", tuple(self.created_schedules))
                self.cursor.execute(f"DELETE FROM class_schedules WHERE id IN ({fmt})", tuple(self.created_schedules))
            self.cursor.execute("DELETE FROM student_absence_alerts WHERE student_id = %s", (self.student_id,))
            self.cursor.execute("DELETE FROM class_enrollments WHERE student_id = %s", (self.student_id,))
            self.cursor.execute("DELETE FROM class_subject_instructors WHERE instructor_id = %s", (self.trainer_user_id,))
            self.cursor.execute("DELETE FROM class_subjects WHERE class_id IN (%s, %s)", (self.class1_id, self.class2_id))
            self.cursor.execute("DELETE FROM classes WHERE id IN (%s, %s)", (self.class1_id, self.class2_id))
            self.cursor.execute("DELETE FROM subjects WHERE id = %s", (self.subject_id,))
            self.cursor.execute("DELETE FROM students WHERE id = %s", (self.student_id,))
            self.cursor.execute("DELETE FROM training_programs WHERE id = %s", (self.program_id,))
            for uid in [self.manager_user_id, self.trainer_user_id, self.student_user_id]:
                self.cursor.execute("DELETE FROM user_roles WHERE user_id = %s", (uid,))
                self.cursor.execute("DELETE FROM users WHERE id = %s", (uid,))
            self.conn.commit()
        except Exception:
            pass
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

    def _create_token(self, user_id: str, roles: list[str]) -> str:
        sid = f"sid-{uuid.uuid4()}"
        self.sessions[sid] = user_id
        with self.app.app_context():
            return create_access_token(
                identity=user_id,
                additional_claims={"roles": roles, "sid": sid},
            )

    def _create_schedules(self, class_id: str, total_count: int, past_count: int) -> list[str]:
        """Tạo lịch học: past_count buổi đã qua, (total_count - past_count) buổi tương lai."""
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
                (sid, class_id, self.subject_id, i + 1, f"Bài học {i + 1}", ld, checked, self.now, self.now),
            )
        self.conn.commit()
        return sched_ids

    def _record_attendance(self, schedule_id: str, student_id: str, status: str):
        self.cursor.execute(
            """
            INSERT INTO session_attendances (id, schedule_id, student_id, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE status = VALUES(status), updated_at = VALUES(updated_at)
            """,
            (str(uuid.uuid4()), schedule_id, student_id, status, self.now, self.now),
        )
        self.conn.commit()

    def test_tc257_10_4_out_of_20_does_not_flag_at_20_percent(self):
        """4/20 buổi tại ngưỡng 20%: Tỷ lệ 20.0% KHÔNG lớn hơn ngưỡng 20%, không bật cờ."""
        # Tạo 20 buổi học (10 buổi đã kết thúc, 10 buổi tương lai -> N = 20)
        scheds = self._create_schedules(self.class1_id, total_count=20, past_count=10)

        # Cho học viên vắng 4 buổi trong số các buổi đã kết thúc
        for i in range(4):
            self._record_attendance(scheds[i], self.student_id, "excused" if i % 2 == 0 else "unexcused")
        # 6 buổi còn lại có mặt
        for i in range(4, 10):
            self._record_attendance(scheds[i], self.student_id, "present")

        results = absence_alert_service.evaluate_class_absence_alerts(self.class1_id, persist=True)
        res = next(r for r in results if r["student_id"] == self.student_id)

        self.assertEqual(res["total_sessions"], 20)
        self.assertEqual(res["absent_sessions"], 4)
        self.assertEqual(res["absence_rate"], 20.0)
        self.assertFalse(res["is_flagged"], "4/20 tại ngưỡng 20% không được bật cờ vì 20% không lớn hơn 20%")
        self.assertEqual(res["status"], "inactive")

        # Kiểm tra bản ghi DB
        db_alert = absence_alert_repository.get_student_absence_alert(self.class1_id, self.student_id)
        self.assertIsNotNone(db_alert)
        self.assertEqual(db_alert["status"], "inactive")

    def test_tc257_11_5_out_of_20_flags_active_at_20_percent(self):
        """5/20 buổi tại ngưỡng 20%: Tỷ lệ 25.0% LỚN HƠN 20%, BẬT CỜ cảnh báo (active)."""
        scheds = self._create_schedules(self.class1_id, total_count=20, past_count=10)

        # Cho học viên vắng 5 buổi
        for i in range(5):
            self._record_attendance(scheds[i], self.student_id, "unexcused")
        for i in range(5, 10):
            self._record_attendance(scheds[i], self.student_id, "present")

        results = absence_alert_service.evaluate_class_absence_alerts(self.class1_id, persist=True)
        res = next(r for r in results if r["student_id"] == self.student_id)

        self.assertEqual(res["total_sessions"], 20)
        self.assertEqual(res["absent_sessions"], 5)
        self.assertEqual(res["absence_rate"], 25.0)
        self.assertTrue(res["is_flagged"], "5/20 = 25% > 20% phải bật cờ")
        self.assertEqual(res["status"], "active")
        self.assertEqual(res["alert_round"], 1)

        db_alert = absence_alert_repository.get_student_absence_alert(self.class1_id, self.student_id)
        self.assertEqual(db_alert["status"], "active")
        self.assertIsNone(db_alert["resolved_at"])

    def test_tc257_12_revising_attendance_turns_flag_off_and_re_exceeding_increments_round(self):
        """Sửa điểm danh về 4/20 làm cờ TẮT (inactive). Khi vượt lại 5/20, alert_round tăng lên 2."""
        scheds = self._create_schedules(self.class1_id, total_count=20, past_count=10)

        # 1. Ban đầu vắng 5 buổi -> bật cờ round 1
        for i in range(5):
            self._record_attendance(scheds[i], self.student_id, "unexcused")
        for i in range(5, 10):
            self._record_attendance(scheds[i], self.student_id, "present")

        r1 = absence_alert_service.evaluate_class_absence_alerts(self.class1_id, persist=True)
        item1 = next(r for r in r1 if r["student_id"] == self.student_id)
        self.assertTrue(item1["is_flagged"])
        self.assertEqual(item1["alert_round"], 1)

        # 2. Sửa buổi thứ 5 từ vắng sang có mặt -> giảm vắng còn 4/20 -> cờ tắt
        self._record_attendance(scheds[4], self.student_id, "present")
        r2 = absence_alert_service.evaluate_class_absence_alerts(self.class1_id, persist=True)
        item2 = next(r for r in r2 if r["student_id"] == self.student_id)
        self.assertFalse(item2["is_flagged"])
        self.assertEqual(item2["status"], "inactive")

        db_alert2 = absence_alert_repository.get_student_absence_alert(self.class1_id, self.student_id)
        self.assertEqual(db_alert2["status"], "inactive")
        self.assertIsNotNone(db_alert2["resolved_at"])

        # 3. Học viên lại vắng ở buổi thứ 6 -> vắng tăng lên 5/20 -> cờ bật lại, alert_round = 2
        self._record_attendance(scheds[5], self.student_id, "unexcused")
        r3 = absence_alert_service.evaluate_class_absence_alerts(self.class1_id, persist=True)
        item3 = next(r for r in r3 if r["student_id"] == self.student_id)
        self.assertTrue(item3["is_flagged"])
        self.assertEqual(item3["status"], "active")
        self.assertEqual(item3["alert_round"], 2, "Đợt cảnh báo mới sau khi đã tắt phải có alert_round = 2")

    def test_tc257_13_two_classes_evaluated_independently(self):
        """Học viên học 2 lớp: Class 1 vượt ngưỡng có cờ, Class 2 dưới ngưỡng không có cờ."""
        # Class 1: 5/20 vắng -> bật cờ
        scheds1 = self._create_schedules(self.class1_id, total_count=20, past_count=10)
        for i in range(5):
            self._record_attendance(scheds1[i], self.student_id, "unexcused")

        # Class 2: 1/20 vắng -> không bật cờ
        scheds2 = self._create_schedules(self.class2_id, total_count=20, past_count=10)
        self._record_attendance(scheds2[0], self.student_id, "unexcused")

        absence_alert_service.evaluate_class_absence_alerts(self.class1_id, persist=True)
        absence_alert_service.evaluate_class_absence_alerts(self.class2_id, persist=True)

        alert_c1 = absence_alert_repository.get_student_absence_alert(self.class1_id, self.student_id)
        alert_c2 = absence_alert_repository.get_student_absence_alert(self.class2_id, self.student_id)

        self.assertEqual(alert_c1["status"], "active")
        self.assertEqual(alert_c2["status"], "inactive")

        # Hồ sơ học viên chỉ liệt kê cảnh báo của Class 1
        profile_alerts = absence_alert_service.get_student_profile_absence_alerts_service(self.student_id)
        self.assertEqual(len(profile_alerts), 1)
        self.assertEqual(profile_alerts[0]["class_id"], self.class1_id)

    def test_tc257_14_future_and_cancelled_sessions_handled_correctly(self):
        """Buổi tương lai không tính vào A; buổi bị hủy loại khỏi cả A và N."""
        # 10 buổi: 5 đã kết thúc, 4 tương lai, 1 bị hủy
        scheds = self._create_schedules(self.class1_id, total_count=10, past_count=5)

        # Hủy 1 buổi tương lai
        self.cursor.execute("UPDATE class_schedules SET status = 'cancelled' WHERE id = %s", (scheds[9],))
        self.conn.commit()

        # Vắng 2 buổi đã kết thúc
        self._record_attendance(scheds[0], self.student_id, "unexcused")
        self._record_attendance(scheds[1], self.student_id, "excused")

        # Buổi tương lai có bản ghi xin nghỉ trước nhưng chưa kết thúc
        self._record_attendance(scheds[6], self.student_id, "excused")

        results = absence_alert_service.evaluate_class_absence_alerts(self.class1_id, persist=False)
        res = next(r for r in results if r["student_id"] == self.student_id)

        # N = 9 (10 - 1 buổi hủy)
        self.assertEqual(res["total_sessions"], 9)
        # A = 2 (buổi tương lai scheds[6] không tính vào A)
        self.assertEqual(res["absent_sessions"], 2)

    def test_tc257_15_api_attendance_summary_includes_absence_alert(self):
        """API GET /api/v1/classes/<id>/attendance-summary trả về trường absence_alert cho từng học viên."""
        scheds = self._create_schedules(self.class1_id, total_count=20, past_count=10)
        for i in range(5):
            self._record_attendance(scheds[i], self.student_id, "unexcused")

        res = self.client.get(
            f"/api/v1/classes/{self.class1_id}/attendance-summary",
            headers={"Authorization": f"Bearer {self.manager_token}"},
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        students = body.get("data", {}).get("students", [])
        self.assertGreaterEqual(len(students), 1)

        stu_item = next(s for s in students if s["student_id"] == self.student_id)
        self.assertIn("absence_alert", stu_item)
        alert = stu_item["absence_alert"]
        self.assertTrue(alert["is_flagged"])
        self.assertEqual(alert["status"], "active")
        self.assertEqual(alert["absent_sessions"], 5)
        self.assertEqual(alert["total_sessions"], 20)
        self.assertEqual(alert["absence_rate"], 25.0)

    def test_tc257_16_api_student_profile_absence_alerts(self):
        """API GET /api/v1/students/<id>/absence-alerts trả về các cảnh báo đang bật."""
        scheds = self._create_schedules(self.class1_id, total_count=20, past_count=10)
        for i in range(5):
            self._record_attendance(scheds[i], self.student_id, "unexcused")

        absence_alert_service.evaluate_class_absence_alerts(self.class1_id, persist=True)

        res = self.client.get(
            f"/api/v1/students/{self.student_id}/absence-alerts",
            headers={"Authorization": f"Bearer {self.manager_token}"},
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "success")
        data = body["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["class_id"], self.class1_id)
        self.assertTrue(data[0]["is_flagged"])
        self.assertIn("25%", data[0]["tooltip"])
