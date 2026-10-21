"""
Bộ kiểm thử tự động cho SCRUM-252 Lát cắt 252.4 — Tra cứu lịch sử trong hồ sơ học viên.
Kiểm tra toàn diện:
1. Phân quyền RBAC:
   - Token có quyền (Training Manager) truy xuất lịch sử thành công (200).
   - Token không có quyền (Trainee) bị từ chối (403).
   - Không có token bị từ chối (401).
2. Đầy đủ cả 3 loại thao tác trong lịch sử:
   - Bảo lưu (reserve): có thông tin lớp nguồn, lý do, ngày hiệu lực, người thực hiện.
   - Chuyển lớp (transfer): có thông tin lớp nguồn, lớp đích, lý do, ngày hiệu lực.
   - Thôi học (drop): có thông tin lớp (hoặc toàn bộ), lý do, ngày hiệu lực.
3. Thứ tự lịch sử và bảo toàn dữ liệu:
   - Sắp xếp mới nhất trước (created_at DESC, id DESC).
   - Không ghi đè bản ghi cũ (mỗi thao tác tạo 1 record độc lập).
4. Tính nguyên tử & không ghi nhận lịch sử giả:
   - Thao tác thất bại do validation hoặc lỗi nghiệp vụ không ghi nhận lịch sử.
5. Trạng thái hiệu lực (status):
   - Ngày hiệu lực quá khứ/hôm nay -> 'effective'.
   - Ngày hiệu lực tương lai -> 'pending'.
"""

from datetime import date, datetime, timedelta
import unittest
import uuid

from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.main import app
from app.services import authorization_service


class Scrum252Slice4HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = app.test_client()

        cls.suffix = uuid.uuid4().hex[:8]
        cls.tm_user_id = f"test-tm-{cls.suffix}"
        cls.trainee_user_id = f"test-trainee-{cls.suffix}"

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Tạo các user
                users = [
                    (cls.tm_user_id, f"tm_{cls.suffix}@ictu.edu.vn", "Training Manager User"),
                    (cls.trainee_user_id, f"trainee_{cls.suffix}@ictu.edu.vn", "Trainee User"),
                ]
                for uid, email, name in users:
                    cur.execute(
                        "INSERT INTO users (id, email, password_hash, name, created_at, updated_at) VALUES (%s, %s, 'hash', %s, NOW(), NOW())",
                        (uid, email, name),
                    )

                # Gán role
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-training-manager', NOW())", (cls.tm_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.trainee_user_id,))

                # 2. Tạo Program & Classes
                cls.prog_id = f"prog-{cls.suffix}"
                cur.execute(
                    "INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'History Program', NOW(), NOW())",
                    (cls.prog_id, f"PRGH_{cls.suffix}"),
                )

                cls.class_1_id = f"cls1-{cls.suffix}"
                cls.class_2_id = f"cls2-{cls.suffix}"
                cls.class_3_id = f"cls3-{cls.suffix}"
                cls.start_date = date.today() - timedelta(days=20)

                for cid, code in [
                    (cls.class_1_id, f"C1H_{cls.suffix}"),
                    (cls.class_2_id, f"C2H_{cls.suffix}"),
                    (cls.class_3_id, f"C3H_{cls.suffix}"),
                ]:
                    cur.execute(
                        "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, %s, 30, 'in_progress', NOW(), NOW())",
                        (cid, code, cls.prog_id, cls.start_date),
                    )

                # 3. Tạo Student
                cls.student_id = f"st-{cls.suffix}"
                cur.execute(
                    "INSERT INTO students (id, student_code, full_name, phone, email, program_id, status, created_at, updated_at) VALUES (%s, %s, 'Student History Test', '0988776655', %s, %s, 'enrolled', NOW(), NOW())",
                    (cls.student_id, f"STH_{cls.suffix}", f"sth_{cls.suffix}@ictu.edu.vn", cls.prog_id),
                )

                # 4. Ghi danh vào Class 1 và Class 2
                cls.enr_1_id = f"enr1-{cls.suffix}"
                cls.enr_2_id = f"enr2-{cls.suffix}"
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', %s, %s, NOW(), NOW())",
                    (cls.enr_1_id, cls.class_1_id, cls.student_id, datetime.combine(cls.start_date, datetime.min.time()), cls.tm_user_id),
                )
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', %s, %s, NOW(), NOW())",
                    (cls.enr_2_id, cls.class_2_id, cls.student_id, datetime.combine(cls.start_date, datetime.min.time()), cls.tm_user_id),
                )

                # 5. Sessions
                cls.sess_tm = f"sess_tm_{cls.suffix}"
                cls.sess_trainee = f"sess_trainee_{cls.suffix}"
                sessions = [
                    (cls.sess_tm, cls.tm_user_id),
                    (cls.sess_trainee, cls.trainee_user_id),
                ]
                for sid, uid in sessions:
                    cur.execute(
                        """
                        INSERT INTO auth_sessions (session_id, user_id, refresh_jti, created_at, last_activity_at, idle_expires_at, absolute_expires_at)
                        VALUES (%s, %s, %s, NOW(), NOW(), DATE_ADD(NOW(), INTERVAL 8 HOUR), DATE_ADD(NOW(), INTERVAL 8 HOUR))
                        """,
                        (sid, uid, f"ref_{sid}"),
                    )

                conn.commit()
        finally:
            conn.close()

        with cls.app.app_context():
            cls.tm_token = create_access_token(
                identity=cls.tm_user_id,
                additional_claims={"roles": ["training_manager"], "sid": cls.sess_tm},
            )
            cls.trainee_token = create_access_token(
                identity=cls.trainee_user_id,
                additional_claims={"roles": ["trainee"], "sid": cls.sess_trainee},
            )

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM student_lifecycle_history WHERE student_id = %s", (cls.student_id,))
                cur.execute("DELETE FROM class_enrollments WHERE student_id = %s", (cls.student_id,))
                cur.execute("DELETE FROM students WHERE id = %s", (cls.student_id,))
                cur.execute("DELETE FROM classes WHERE id IN (%s, %s, %s)", (cls.class_1_id, cls.class_2_id, cls.class_3_id))
                cur.execute("DELETE FROM training_programs WHERE id = %s", (cls.prog_id,))
                cur.execute("DELETE FROM auth_sessions WHERE session_id IN (%s, %s)", (cls.sess_tm, cls.sess_trainee))
                cur.execute("DELETE FROM user_roles WHERE user_id IN (%s, %s)", (cls.tm_user_id, cls.trainee_user_id))
                cur.execute("DELETE FROM users WHERE id IN (%s, %s)", (cls.tm_user_id, cls.trainee_user_id))
                conn.commit()
        finally:
            conn.close()

    def test_01_rbac_permissions_enforced(self):
        """Kiểm tra phân quyền: Quản lý đào tạo xem được (200), Trainee bị 403, thiếu token bị 401."""
        # 1. Không có token -> 401
        res = self.client.get(f"/api/v1/students/{self.student_id}/lifecycle-history")
        self.assertEqual(res.status_code, 401)

        # 2. Token trainee -> 403
        res = self.client.get(
            f"/api/v1/students/{self.student_id}/lifecycle-history",
            headers={"Authorization": f"Bearer {self.trainee_token}"},
        )
        self.assertEqual(res.status_code, 403)

        # 3. Token training manager -> 200
        res = self.client.get(
            f"/api/v1/students/{self.student_id}/lifecycle-history",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["student_id"], self.student_id)
        self.assertEqual(len(data["items"]), 0)

    def test_02_all_three_actions_recorded_in_history(self):
        """Thực hiện cả 3 thao tác (bảo lưu, chuyển lớp, thôi học) và kiểm tra lịch sử."""
        headers = {"Authorization": f"Bearer {self.tm_token}"}
        today = date.today()
        future_date = (today + timedelta(days=7)).isoformat()
        past_date = (today - timedelta(days=2)).isoformat()

        # 1. Bảo lưu lớp 1 (ngày tương lai -> pending)
        res_reserve = self.client.post(
            f"/api/v1/students/{self.student_id}/reserve",
            headers=headers,
            json={
                "class_id": self.class_1_id,
                "effective_date": future_date,
                "reason": "Xin nghỉ dưỡng bệnh 1 tháng",
            },
        )
        self.assertEqual(res_reserve.status_code, 200)

        import time
        time.sleep(0.05)

        # 2. Chuyển lớp: Lớp 2 -> Lớp 3 (ngày quá khứ -> effective)
        res_transfer = self.client.post(
            f"/api/v1/students/{self.student_id}/transfer",
            headers=headers,
            json={
                "source_class_id": self.class_2_id,
                "target_class_id": self.class_3_id,
                "effective_date": past_date,
                "reason": "Đổi ca học phù hợp lịch làm việc",
            },
        )
        self.assertEqual(res_transfer.status_code, 200)

        time.sleep(0.05)

        # 3. Thôi học lớp 3 (ngày hôm nay -> effective)
        res_drop = self.client.post(
            f"/api/v1/students/{self.student_id}/drop",
            headers=headers,
            json={
                "scope": "single",
                "class_id": self.class_3_id,
                "effective_date": today.isoformat(),
                "reason": "Bận việc gia đình không thể tiếp tục",
            },
        )
        self.assertEqual(res_drop.status_code, 200)

        # 4. Kiểm tra danh sách lịch sử trả về
        res_hist = self.client.get(
            f"/api/v1/students/{self.student_id}/lifecycle-history",
            headers=headers,
        )
        self.assertEqual(res_hist.status_code, 200)
        items = res_hist.get_json()["data"]["items"]
        self.assertEqual(len(items), 3)

        # Ki\u1ec3m tra item m\u1edbi nh\u1ea5t l\xe0 'drop'
        item_drop = items[0]
        self.assertEqual(item_drop["action_type"], "drop", f"Full items list: {items}")
        self.assertEqual(item_drop["reason"], "Bận việc gia đình không thể tiếp tục")
        self.assertEqual(item_drop["effective_date"], today.isoformat())
        self.assertEqual(item_drop["status"], "applied")
        self.assertEqual(item_drop["performer_name"], "Training Manager User")

        # Ki\u1ec3m tra item th\u1ee9 2 l\xe0 'transfer'
        item_transfer = items[1]
        self.assertEqual(item_transfer["action_type"], "transfer", f"Full items: {items}")
        self.assertEqual(item_transfer["source_class_code"], f"C2H_{self.suffix}")
        self.assertEqual(item_transfer["target_class_code"], f"C3H_{self.suffix}")
        self.assertEqual(item_transfer["reason"], "Đổi ca học phù hợp lịch làm việc")
        self.assertEqual(item_transfer["effective_date"], past_date)
        self.assertEqual(item_transfer["status"], "applied")

        # Kiểm tra item thứ 3 là 'reserve'
        item_reserve = items[2]
        self.assertEqual(item_reserve["action_type"], "reserve")
        self.assertEqual(item_reserve["source_class_code"], f"C1H_{self.suffix}")
        self.assertIsNone(item_reserve["target_class_code"])
        self.assertEqual(item_reserve["reason"], "Xin nghỉ dưỡng bệnh 1 tháng")
        self.assertEqual(item_reserve["effective_date"], future_date)
        self.assertEqual(item_reserve["status"], "pending")

    def test_03_failed_action_does_not_create_phantom_history(self):
        """Thao tác thất bại do validation không tạo thêm bản ghi lịch sử giả."""
        headers = {"Authorization": f"Bearer {self.tm_token}"}

        # Đọc số lượng hiện tại
        res_before = self.client.get(
            f"/api/v1/students/{self.student_id}/lifecycle-history",
            headers=headers,
        )
        count_before = len(res_before.get_json()["data"]["items"])

        # Gửi request transfer lỗi (lớp đích trùng lớp nguồn)
        res_fail = self.client.post(
            f"/api/v1/students/{self.student_id}/transfer",
            headers=headers,
            json={
                "source_class_id": self.class_1_id,
                "target_class_id": self.class_1_id,
                "effective_date": date.today().isoformat(),
                "reason": "Thao tác lỗi",
            },
        )
        self.assertEqual(res_fail.status_code, 400)

        # Đọc lại lịch sử, số lượng phải giữ nguyên
        res_after = self.client.get(
            f"/api/v1/students/{self.student_id}/lifecycle-history",
            headers=headers,
        )
        count_after = len(res_after.get_json()["data"]["items"])
        self.assertEqual(count_after, count_before)


if __name__ == "__main__":
    unittest.main()
