"""
Kiểm thử tích hợp dữ liệu thật trên Database kiểm thử riêng (training_management_test).
Xác minh toàn bộ các yêu cầu nghiệm thu SCRUM-228 & Phân quyền Lịch:
1. Tạo một lớp thực tế có:
   - Một giảng viên chính (class_subject_instructors role_type='main').
   - Một trợ giảng (class_subject_instructors role_type='assistant').
   - Một giảng viên khác dạy thay một buổi (class_schedules.instructor_id).
   - Một tài khoản đồng thời trainer + trainee.
2. Kiểm tra bằng dữ liệu thật:
   - Mỗi người nhìn thấy đúng lịch và nhãn vai trò:
     + Giảng viên chính: 'Giảng viên chính' ở các buổi họ dạy, 'Giảng viên môn (Dạy thay bởi ...)' ở buổi được dạy thay.
     + Trợ giảng: 'Trợ giảng' ở các buổi của môn.
     + Giảng viên dạy thay: 'Giảng viên dạy thay' ở đúng buổi họ dạy thay, KHÔNG thấy các buổi khác của lớp.
   - Buổi dạy thay: Giảng viên chính vẫn theo dõi được tiến độ môn học nhưng buổi đó không tính là buổi họ phải trực tiếp dạy.
   - 'Buổi tiếp theo' (next_session): Tính theo người thực sự tham gia buổi học (giảng viên trực tiếp dạy hoặc trợ giảng).
   - Phát hiện xung đột lịch: Báo trùng lịch theo người thực sự tham gia buổi học (giảng viên dạy thay), không báo sai cho giảng viên chính.
   - Không trùng buổi do kết hợp phân công theo môn và theo buổi (SELECT DISTINCT).
   - Giảng viên KHÔNG xem được lịch học viên bất kỳ (/students/<id>/schedule) -> 403 Forbidden.
   - Giảng viên KHÔNG mở rộng được phạm vi /calendar bằng tham số API (?instructor_id=other) -> bị backend giới hạn chặt chẽ.
   - Tài khoản trainer + trainee chuyển đổi context=learning và context=teaching mượt mà, không hiển thị nhầm dữ liệu.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import unittest
import uuid
from flask_jwt_extended import create_access_token

# Thiết lập database kiểm thử riêng
os.environ["DB_NAME"] = "training_management_test"

from app.database.connection import get_db_connection, reset_db_pool
from app.main import app
from app.models.login_session import LoginSession
from app.repositories import class_schedule_repository
from app.services import schedule_service


class TestScrum228RealDatabaseVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset_db_pool()
        cls.conn = get_db_connection()
        cls.prefix = f"v228_{uuid.uuid4().hex[:6]}"

        # Định danh các thực thể kiểm thử
        cls.prog_id = f"prog_{cls.prefix}"
        cls.prog_other_id = f"prog_oth_{cls.prefix}"
        cls.sub_id = f"sub_{cls.prefix}"
        cls.sub_other_id = f"sub_oth_{cls.prefix}"
        cls.class_id = f"cls_{cls.prefix}"
        cls.class_other_id = f"cls_oth_{cls.prefix}"
        cls.class_sub_id = f"cs_{cls.prefix}"
        cls.class_sub_other_id = f"cs_oth_{cls.prefix}"
        cls.room_id = f"room_{cls.prefix}"

        # 4 người dùng theo yêu cầu
        cls.u_main = f"u_main_{cls.prefix}"
        cls.u_assistant = f"u_asst_{cls.prefix}"
        cls.u_substitute = f"u_subst_{cls.prefix}"
        cls.u_dual = f"u_dual_{cls.prefix}"
        cls.u_pure_student = f"u_stu_{cls.prefix}"
        cls.student_record_id = f"strec_{cls.prefix}"
        cls.dual_student_record_id = f"strec_dual_{cls.prefix}"

        # 3 buổi học
        cls.sch_1 = f"sch1_{cls.prefix}"
        cls.sch_2 = f"sch2_{cls.prefix}"
        cls.sch_3 = f"sch3_{cls.prefix}"
        cls.sch_dual_teach = f"sch_dt_{cls.prefix}"

        with cls.conn.cursor() as cur:
            # 1. Tạo phòng học
            cur.execute(
                """
                INSERT INTO classrooms (id, room_code, room_name, room_type, capacity, status, created_at, updated_at)
                VALUES (%s, %s, %s, 'offline', 40, 'active', NOW(), NOW())
                """,
                (cls.room_id, f"LAB-{cls.prefix.upper()}", f"Phòng Lab {cls.prefix.upper()}"),
            )

            # 2. Tạo chương trình đào tạo & môn học
            cur.execute(
                """
                INSERT INTO training_programs (id, code, name, description, duration_semesters, status, created_at, updated_at)
                VALUES (%s, %s, 'Chương trình Phân tán', 'Mô tả', 8, 'active', NOW(), NOW())
                """,
                (cls.prog_id, f"PRG_{cls.prefix.upper()}"),
            )
            cur.execute(
                """
                INSERT INTO training_programs (id, code, name, description, duration_semesters, status, created_at, updated_at)
                VALUES (%s, %s, 'Chương trình An ninh mạng', 'Mô tả', 8, 'active', NOW(), NOW())
                """,
                (cls.prog_other_id, f"PRG_OTH_{cls.prefix.upper()}"),
            )

            cur.execute(
                """
                INSERT INTO subjects (id, code, name, description, credits, total_sessions, status, created_at, updated_at)
                VALUES (%s, %s, 'Điện toán Đám mây', 'Môn học Đám mây', 3, 15, 'active', NOW(), NOW())
                """,
                (cls.sub_id, f"CLOUD_{cls.prefix.upper()}"),
            )
            cur.execute(
                """
                INSERT INTO subjects (id, code, name, description, credits, total_sessions, status, created_at, updated_at)
                VALUES (%s, %s, 'An ninh Hệ thống', 'Môn An ninh', 3, 15, 'active', NOW(), NOW())
                """,
                (cls.sub_other_id, f"SEC_{cls.prefix.upper()}"),
            )

            # 3. Tạo lớp học
            cur.execute(
                """
                INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, learning_mode, status, created_at, updated_at)
                VALUES (%s, %s, %s, '2026-10-01', 35, 'offline', 'in_progress', NOW(), NOW())
                """,
                (cls.class_id, f"CNTT-{cls.prefix.upper()}", cls.prog_id),
            )
            cur.execute(
                """
                INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, learning_mode, status, created_at, updated_at)
                VALUES (%s, %s, %s, '2026-10-01', 35, 'offline', 'in_progress', NOW(), NOW())
                """,
                (cls.class_other_id, f"ANM-{cls.prefix.upper()}", cls.prog_other_id),
            )

            # 4. Gắn môn vào lớp
            cur.execute(
                """
                INSERT INTO class_subjects (id, class_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at)
                VALUES (%s, %s, %s, 1, 1, 1, NOW(), NOW())
                """,
                (cls.class_sub_id, cls.class_id, cls.sub_id),
            )
            cur.execute(
                """
                INSERT INTO class_subjects (id, class_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at)
                VALUES (%s, %s, %s, 1, 1, 1, NOW(), NOW())
                """,
                (cls.class_sub_other_id, cls.class_other_id, cls.sub_other_id),
            )

            # 5. Tạo Users
            users_data = [
                (cls.u_main, f"main_{cls.prefix}@ictu.edu.vn", "TS. Lê Văn Chính (GV Chính)", "trainer"),
                (cls.u_assistant, f"asst_{cls.prefix}@ictu.edu.vn", "ThS. Hoàng Thị Trợ Giảng", "trainer"),
                (cls.u_substitute, f"subst_{cls.prefix}@ictu.edu.vn", "TS. Phạm Văn Dạy Thay", "trainer"),
                (cls.u_dual, f"dual_{cls.prefix}@ictu.edu.vn", "Vũ Văn Đa Năng (Dual Trainer-Trainee)", "trainer"),
                (cls.u_pure_student, f"stu_{cls.prefix}@ictu.edu.vn", "Trần Thị Sinh Viên", "trainee"),
            ]
            for uid, email, name, primary_role in users_data:
                cur.execute(
                    """
                    INSERT INTO users (id, email, name, password_hash, role, status, must_change_password, created_at, updated_at)
                    VALUES (%s, %s, %s, 'hash-dummy', %s, 'active', 0, NOW(), NOW())
                    """,
                    (uid, email, name, primary_role),
                )

            # 6. Gán vai trò trong user_roles
            cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.u_main,))
            cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.u_assistant,))
            cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.u_substitute,))
            cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.u_pure_student,))
            # Tài khoản Dual-role có cả trainer và trainee
            cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.u_dual,))
            cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.u_dual,))

            # 7. Phân công giảng viên chính và trợ giảng theo môn (class_subject_instructors)
            # Giảng viên chính: cls.u_main
            cur.execute(
                """
                INSERT INTO class_subject_instructors (id, class_subject_id, instructor_id, role_type, created_at, updated_at)
                VALUES (%s, %s, %s, 'main', NOW(), NOW())
                """,
                (f"csi_m_{cls.prefix}", cls.class_sub_id, cls.u_main),
            )
            # Trợ giảng: cls.u_assistant
            cur.execute(
                """
                INSERT INTO class_subject_instructors (id, class_subject_id, instructor_id, role_type, created_at, updated_at)
                VALUES (%s, %s, %s, 'assistant', NOW(), NOW())
                """,
                (f"csi_a_{cls.prefix}", cls.class_sub_id, cls.u_assistant),
            )
            # Dual-role user: phân công dạy lớp ANM-K20B
            cur.execute(
                """
                INSERT INTO class_subject_instructors (id, class_subject_id, instructor_id, role_type, created_at, updated_at)
                VALUES (%s, %s, %s, 'main', NOW(), NOW())
                """,
                (f"csi_dual_{cls.prefix}", cls.class_sub_other_id, cls.u_dual),
            )

            # 8. Tạo hồ sơ học viên & ghi danh
            # Sinh viên thuần túy
            cur.execute(
                """
                INSERT INTO students (id, student_code, user_id, full_name, phone, email, program_id, status, created_at, updated_at)
                VALUES (%s, %s, %s, 'Trần Thị Sinh Viên', '0912345678', %s, %s, 'active', NOW(), NOW())
                """,
                (cls.student_record_id, f"STU_{cls.prefix.upper()}", cls.u_pure_student, f"stu_{cls.prefix}@ictu.edu.vn", cls.prog_id),
            )
            cur.execute(
                """
                INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at)
                VALUES (%s, %s, %s, 'enrolled', NOW(), %s, NOW(), NOW())
                """,
                (f"enr_stu_{cls.prefix}", cls.class_id, cls.student_record_id, cls.u_main),
            )
            # Dual-role user: có hồ sơ sinh viên và ghi danh học lớp CNTT
            cur.execute(
                """
                INSERT INTO students (id, student_code, user_id, full_name, phone, email, program_id, status, created_at, updated_at)
                VALUES (%s, %s, %s, 'Vũ Văn Đa Năng', '0987654321', %s, %s, 'active', NOW(), NOW())
                """,
                (cls.dual_student_record_id, f"STU_DUAL_{cls.prefix.upper()}", cls.u_dual, f"dual_{cls.prefix}@ictu.edu.vn", cls.prog_id),
            )
            cur.execute(
                """
                INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at)
                VALUES (%s, %s, %s, 'enrolled', NOW(), %s, NOW(), NOW())
                """,
                (f"enr_dual_{cls.prefix}", cls.class_id, cls.dual_student_record_id, cls.u_main),
            )

            # 9. Tạo 3 buổi học trong tuần từ 2026-10-12 đến 2026-10-18
            # Buổi 1: Thứ 3 (2026-10-13) 07:30 - 09:30 -> Giảng viên chính (u_main) dạy
            cur.execute(
                """
                INSERT INTO class_schedules (id, class_id, class_subject_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, room_id, instructor_id, status, attendance_checked, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 1, 'Kiến trúc hệ thống phân tán', '2026-10-13', 'Ca 1 (07:30 - 09:30)', '07:30:00', '09:30:00', %s, %s, 'scheduled', 0, NOW(), NOW())
                """,
                (cls.sch_1, cls.class_id, cls.class_sub_id, cls.sub_id, cls.room_id, cls.u_main),
            )

            # Buổi 2: Thứ 5 (2026-10-15) 07:30 - 09:30 -> Giảng viên dạy thay (u_substitute) dạy!
            cur.execute(
                """
                INSERT INTO class_schedules (id, class_id, class_subject_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, room_id, instructor_id, status, attendance_checked, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 2, 'Containerization với Docker và Kubernetes', '2026-10-15', 'Ca 1 (07:30 - 09:30)', '07:30:00', '09:30:00', %s, %s, 'scheduled', 0, NOW(), NOW())
                """,
                (cls.sch_2, cls.class_id, cls.class_sub_id, cls.sub_id, cls.room_id, cls.u_substitute),
            )

            # Buổi 3: Thứ 7 (2026-10-17) 07:30 - 09:30 -> Giảng viên chính (u_main) trực tiếp dạy
            cur.execute(
                """
                INSERT INTO class_schedules (id, class_id, class_subject_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, room_id, instructor_id, status, attendance_checked, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 3, 'Thực hành triển khai Microservices', '2026-10-17', 'Ca 1 (07:30 - 09:30)', '07:30:00', '09:30:00', %s, %s, 'scheduled', 0, NOW(), NOW())
                """,
                (cls.sch_3, cls.class_id, cls.class_sub_id, cls.sub_id, cls.room_id, cls.u_main),
            )

            # Buổi dạy của Dual user bên lớp ANM: Thứ 4 (2026-10-14) 13:30 - 15:30
            cur.execute(
                """
                INSERT INTO class_schedules (id, class_id, class_subject_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, room_id, instructor_id, status, attendance_checked, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 1, 'Nguyên lý phòng thủ mạng', '2026-10-14', 'Ca 3 (13:30 - 15:30)', '13:30:00', '15:30:00', %s, %s, 'scheduled', 0, NOW(), NOW())
                """,
                (cls.sch_dual_teach, cls.class_other_id, cls.class_sub_other_id, cls.sub_other_id, cls.room_id, cls.u_dual),
            )

            cls.conn.commit()

        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        with cls.conn.cursor() as cur:
            cur.execute("DELETE FROM class_schedules WHERE class_id IN (%s, %s)", (cls.class_id, cls.class_other_id))
            cur.execute("DELETE FROM class_enrollments WHERE class_id = %s", (cls.class_id,))
            cur.execute("DELETE FROM students WHERE id IN (%s, %s)", (cls.student_record_id, cls.dual_student_record_id))
            cur.execute("DELETE FROM class_subject_instructors WHERE class_subject_id IN (%s, %s)", (cls.class_sub_id, cls.class_sub_other_id))
            cur.execute("DELETE FROM class_subjects WHERE id IN (%s, %s)", (cls.class_sub_id, cls.class_sub_other_id))
            cur.execute("DELETE FROM classes WHERE id IN (%s, %s)", (cls.class_id, cls.class_other_id))
            cur.execute("DELETE FROM subjects WHERE id IN (%s, %s)", (cls.sub_id, cls.sub_other_id))
            cur.execute("DELETE FROM training_programs WHERE id IN (%s, %s)", (cls.prog_id, cls.prog_other_id))
            cur.execute("DELETE FROM classrooms WHERE id = %s", (cls.room_id,))
            cur.execute("DELETE FROM user_roles WHERE user_id IN (%s, %s, %s, %s, %s)", (cls.u_main, cls.u_assistant, cls.u_substitute, cls.u_dual, cls.u_pure_student))
            cur.execute("DELETE FROM auth_sessions WHERE user_id IN (%s, %s, %s, %s, %s)", (cls.u_main, cls.u_assistant, cls.u_substitute, cls.u_dual, cls.u_pure_student))
            cur.execute("DELETE FROM users WHERE id IN (%s, %s, %s, %s, %s)", (cls.u_main, cls.u_assistant, cls.u_substitute, cls.u_dual, cls.u_pure_student))
            cls.conn.commit()
        cls.conn.close()

    def _make_auth_header(self, user_id: str, roles: list[str]) -> dict:
        sess_id = f"sess_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        # Tạo session trong bảng auth_sessions của CSDL thật
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_sessions (session_id, user_id, refresh_jti, created_at, last_activity_at, idle_expires_at, absolute_expires_at)
                VALUES (%s, %s, %s, NOW(), NOW(), DATE_ADD(NOW(), INTERVAL 8 HOUR), DATE_ADD(NOW(), INTERVAL 8 HOUR))
                """,
                (sess_id, user_id, f"ref_{sess_id}"),
            )
            self.conn.commit()

        with app.app_context():
            token = create_access_token(
                identity=user_id,
                additional_claims={"roles": roles, "sid": sess_id},
            )
            return {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

    # -------------------------------------------------------------
    # 1. Kiểm tra Giảng viên chính (TS. Lê Văn Chính)
    # -------------------------------------------------------------
    def test_01_main_instructor_schedule_and_role_labels(self):
        """Giảng viên chính: Nhìn thấy 3 buổi, nhận diện nhãn 'Giảng viên chính' và 'Giảng viên môn (Dạy thay bởi ...)'."""
        headers = self._make_auth_header(self.u_main, ["trainer"])
        resp = self.client.get(
            "/api/v1/schedules/my-schedule?date_from=2026-10-12&date_to=2026-10-18",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)["data"]

        self.assertEqual(data["user_type"], "trainer")
        self.assertEqual(data["active_context"], "teaching")
        self.assertEqual(len(data["week_sessions"]), 3)

        sessions_by_id = {s["id"]: s for s in data["week_sessions"]}

        # Buổi 1: Do chính GV chính dạy
        s1 = sessions_by_id[self.sch_1]
        self.assertEqual(s1["teaching_role"], "main")
        self.assertEqual(s1["teaching_role_label"], "Giảng viên chính")

        # Buổi 2: Buổi được người khác dạy thay
        s2 = sessions_by_id[self.sch_2]
        self.assertEqual(s2["teaching_role"], "main_delegated")
        self.assertIn("Dạy thay bởi TS. Phạm Văn Dạy Thay", s2["teaching_role_label"])
        # Xác minh: Buổi dạy thay này KHÔNG tính là buổi họ phải trực tiếp dạy
        self.assertNotEqual(s2["instructor_id"], self.u_main)
        self.assertEqual(s2["instructor_id"], self.u_substitute)

        # Buổi 3: Do chính GV chính dạy
        s3 = sessions_by_id[self.sch_3]
        self.assertEqual(s3["teaching_role"], "main")
        self.assertEqual(s3["teaching_role_label"], "Giảng viên chính")

    def test_02_main_instructor_next_session_excludes_delegated_session(self):
        """Buổi tiếp theo (next_session): Tính theo người thực sự tham gia dạy. Buổi dạy thay không được coi là next_session của GV chính."""
        headers = self._make_auth_header(self.u_main, ["trainer"])
        # Đặt mốc thời gian là 2026-10-14 (ở giữa Buổi 1 ngày 13 và Buổi 2 ngày 15)
        resp = self.client.get(
            "/api/v1/schedules/my-schedule?ref_date=2026-10-14&ref_time=00:00:00&date_from=2026-10-12&date_to=2026-10-18",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)["data"]

        next_s = data["next_session"]
        self.assertIsNotNone(next_s)
        # Buổi tiếp theo mà GV chính PHẢI TRỰC TIẾP DẠY là Buổi 3 (ngày 17), KHÔNG PHẢI Buổi 2 (ngày 15 do người khác dạy thay)!
        self.assertEqual(next_s["id"], self.sch_3)
        self.assertEqual(next_s["learning_date"], "2026-10-17")
        self.assertEqual(next_s["teaching_role"], "main")

    # -------------------------------------------------------------
    # 2. Kiểm tra Giảng viên dạy thay (TS. Phạm Văn Dạy Thay)
    # -------------------------------------------------------------
    def test_03_substitute_instructor_schedule_isolation(self):
        """Giảng viên dạy thay: Chỉ nhìn thấy DUY NHẤT buổi mình dạy thay, không bị lộ các buổi khác của lớp."""
        headers = self._make_auth_header(self.u_substitute, ["trainer"])
        resp = self.client.get(
            "/api/v1/schedules/my-schedule?date_from=2026-10-12&date_to=2026-10-18",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)["data"]

        self.assertEqual(data["user_type"], "trainer")
        self.assertEqual(len(data["week_sessions"]), 1)

        s2 = data["week_sessions"][0]
        self.assertEqual(s2["id"], self.sch_2)
        self.assertEqual(s2["teaching_role"], "substitute")
        self.assertEqual(s2["teaching_role_label"], "Giảng viên dạy thay")
        self.assertEqual(s2["instructor_id"], self.u_substitute)

    def test_04_substitute_instructor_next_session(self):
        """Giảng viên dạy thay: Tại mốc 2026-10-14, buổi tiếp theo chính là Buổi 2 (ngày 15) mà họ thực sự tham gia dạy."""
        headers = self._make_auth_header(self.u_substitute, ["trainer"])
        resp = self.client.get(
            "/api/v1/schedules/my-schedule?ref_date=2026-10-14&ref_time=00:00:00&date_from=2026-10-12&date_to=2026-10-18",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)["data"]

        next_s = data["next_session"]
        self.assertIsNotNone(next_s)
        self.assertEqual(next_s["id"], self.sch_2)
        self.assertEqual(next_s["learning_date"], "2026-10-15")
        self.assertEqual(next_s["teaching_role"], "substitute")

    # -------------------------------------------------------------
    # 3. Kiểm tra Trợ giảng (ThS. Hoàng Thị Trợ Giảng)
    # -------------------------------------------------------------
    def test_05_assistant_instructor_schedule_and_badge(self):
        """Trợ giảng: Nhìn thấy các buổi của môn với nhãn 'Trợ giảng'."""
        headers = self._make_auth_header(self.u_assistant, ["trainer"])
        resp = self.client.get(
            "/api/v1/schedules/my-schedule?date_from=2026-10-12&date_to=2026-10-18",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)["data"]

        self.assertEqual(data["user_type"], "trainer")
        self.assertEqual(len(data["week_sessions"]), 3)

        for s in data["week_sessions"]:
            self.assertEqual(s["teaching_role"], "assistant")
            self.assertEqual(s["teaching_role_label"], "Trợ giảng")

    # -------------------------------------------------------------
    # 4. Kiểm tra phát hiện xung đột theo người thực sự tham gia buổi học
    # -------------------------------------------------------------
    def test_06_conflict_detection_by_actual_participating_instructor(self):
        """Kiểm tra xung đột thời khóa biểu: Báo trùng theo người thực sự dạy (u_substitute), không báo nhầm cho GV chính (u_main)."""
        # Kiểm tra slot ngày 2026-10-15 lúc 07:30 - 09:30 (trùng giờ Buổi 2)
        # TH1: Xếp cho Giảng viên dạy thay (u_substitute) -> PHÁT HIỆN TRÙNG LỊCH!
        conflicts_subst = class_schedule_repository.find_conflicts_for_slot(
            learning_date="2026-10-15",
            start_time="07:30:00",
            end_time="09:30:00",
            instructor_id=self.u_substitute,
            room_id=None,
        )
        self.assertGreaterEqual(len(conflicts_subst), 1)
        self.assertEqual(conflicts_subst[0]["id"], self.sch_2)
        self.assertEqual(conflicts_subst[0]["instructor_id"], self.u_substitute)

        # TH2: Xếp cho Giảng viên chính (u_main) vào cùng khung giờ đó -> KHÔNG BỊ TRÙNG!
        # Vì buổi 2 đã có người khác dạy thay, TS. Lê Văn Chính không tham gia dạy ca này nên không bị xung đột lịch!
        conflicts_main = class_schedule_repository.find_conflicts_for_slot(
            learning_date="2026-10-15",
            start_time="07:30:00",
            end_time="09:30:00",
            instructor_id=self.u_main,
            room_id=None,
        )
        self.assertEqual(len(conflicts_main), 0)

    # -------------------------------------------------------------
    # 5. Kiểm tra bảo mật phân quyền: Giảng viên bị chặn xem lịch học viên
    # -------------------------------------------------------------
    def test_07_instructors_strictly_forbidden_from_student_schedule_api(self):
        """Giảng viên cố tình gọi /students/<student_id>/schedule -> Bị chặn 403 Forbidden."""
        # 1. Giảng viên chính
        h_main = self._make_auth_header(self.u_main, ["trainer"])
        r1 = self.client.get(f"/api/v1/students/{self.student_record_id}/schedule", headers=h_main)
        self.assertEqual(r1.status_code, 403)
        self.assertEqual(r1.get_json().get("code"), "FORBIDDEN")

        # 2. Giảng viên dạy thay
        h_subst = self._make_auth_header(self.u_substitute, ["trainer"])
        r2 = self.client.get(f"/api/v1/students/{self.student_record_id}/schedule", headers=h_subst)
        self.assertEqual(r2.status_code, 403)

        # 3. Trợ giảng
        h_asst = self._make_auth_header(self.u_assistant, ["trainer"])
        r3 = self.client.get(f"/api/v1/students/{self.student_record_id}/schedule", headers=h_asst)
        self.assertEqual(r3.status_code, 403)

    # -------------------------------------------------------------
    # 6. Kiểm tra giới hạn phạm vi /calendar: Không mở rộng được bằng tham số
    # -------------------------------------------------------------
    def test_08_calendar_api_strictly_scoped_for_trainers(self):
        """Giảng viên gọi /calendar?instructor_id=other -> Backend ép trainer_scope_user_id của chính họ."""
        h_subst = self._make_auth_header(self.u_substitute, ["trainer"])
        # Cố tình truyền instructor_id của giảng viên chính để xem lén
        resp = self.client.get(
            f"/api/v1/schedules/calendar?date_from=2026-10-12&date_to=2026-10-18&instructor_id={self.u_main}",
            headers=h_subst,
        )
        self.assertEqual(resp.status_code, 200)
        schedules = resp.get_json()["data"]["schedules"]
        # Chỉ thấy duy nhất Buổi 2 của chính mình, không lộ Buổi 1 hoặc Buổi 3 của GV chính
        self.assertEqual(len(schedules), 1)
        self.assertEqual(schedules[0]["id"], self.sch_2)
        self.assertEqual(schedules[0]["instructor_id"], self.u_substitute)

    # -------------------------------------------------------------
    # 7. Kiểm tra tài khoản Trainer + Trainee chuyển đổi ngữ cảnh
    # -------------------------------------------------------------
    def test_09_dual_role_trainer_trainee_context_switching(self):
        """Tài khoản có cả trainer và trainee đổi ngữ cảnh context=learning và context=teaching mượt mà."""
        h_dual = self._make_auth_header(self.u_dual, ["trainer", "trainee"])

        # Ngữ cảnh 1: context=learning (Lịch học của tôi)
        r_learn = self.client.get(
            "/api/v1/schedules/my-schedule?context=learning&date_from=2026-10-12&date_to=2026-10-18",
            headers=h_dual,
        )
        self.assertEqual(r_learn.status_code, 200)
        d_learn = r_learn.get_json()["data"]
        self.assertEqual(d_learn["active_context"], "learning")
        self.assertEqual(d_learn["user_type"], "trainee")
        self.assertEqual(d_learn["student"]["student_code"], f"STU_DUAL_{self.prefix.upper()}")
        self.assertIn("learning", d_learn["available_contexts"])
        self.assertIn("teaching", d_learn["available_contexts"])
        self.assertEqual(len(d_learn["enrolled_classes"]), 1)
        self.assertEqual(d_learn["enrolled_classes"][0]["class_code"], f"CNTT-{self.prefix.upper()}")

        # Ngữ cảnh 2: context=teaching (Lịch giảng dạy của tôi)
        r_teach = self.client.get(
            "/api/v1/schedules/my-schedule?context=teaching&date_from=2026-10-12&date_to=2026-10-18",
            headers=h_dual,
        )
        self.assertEqual(r_teach.status_code, 200)
        d_teach = r_teach.get_json()["data"]
        self.assertEqual(d_teach["active_context"], "teaching")
        self.assertEqual(d_teach["user_type"], "trainer")
        self.assertEqual(d_teach["instructor"]["id"], self.u_dual)
        self.assertEqual(len(d_teach["assigned_classes"]), 1)
        self.assertEqual(d_teach["assigned_classes"][0]["class_code"], f"ANM-{self.prefix.upper()}")
        self.assertEqual(len(d_teach["week_sessions"]), 1)
        self.assertEqual(d_teach["week_sessions"][0]["id"], self.sch_dual_teach)
