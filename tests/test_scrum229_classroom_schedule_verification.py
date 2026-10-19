"""
Kiểm thử tích hợp chuyên biệt: Quản lý phòng học trong sinh lịch và sửa/dời buổi học (SCRUM-229).
1. Chọn phòng từ danh mục chuẩn (vật lý & trực tuyến).
2. Kiểm tra phòng tồn tại và trạng thái khả dụng.
3. Kiểm tra trùng phòng theo ngày, giờ, loại trừ chính buổi đang sửa.
4. Cảnh báo sức chứa khi sĩ số lớp vượt sức chứa phòng vật lý.
5. Phòng trực tuyến lấy liên kết online_link từ danh mục phòng.
6. Xử lý dữ liệu phòng cũ (như 'P301'):
   - Không bị xóa hoặc gán nhầm.
   - Sửa các trường khác không làm mất dữ liệu phòng cũ.
   - Ánh xạ sang danh mục khi xác định duy nhất.
7. Bỏ phòng (Chưa xếp phòng - gửi null).
"""

from datetime import date, datetime, timedelta, timezone
import os
import unittest
import uuid
from flask_jwt_extended import create_access_token

os.environ["DB_NAME"] = "training_management_test"

from app.database.connection import get_db_connection
from app.main import app
from app.models.classroom import Classroom
from app.models.class_schedule import ClassSchedule
from app.repositories import classroom_repository, class_schedule_repository


class TestScrum229ClassroomScheduleVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = cls.app.test_client()

        # Dọn dẹp dữ liệu cũ của test
        cls.clean_db()

        # Tạo lớp học test
        cls.class_id = f"cls_229_{uuid.uuid4().hex[:8]}"
        cls.class_code = f"L_229_{uuid.uuid4().hex[:6]}"
        cls.manager_user_id = f"u_mgr_229_{uuid.uuid4().hex[:8]}"
        cls.instructor_user_id = f"u_ins_229_{uuid.uuid4().hex[:8]}"
        cls.session_id = f"sid_229_{uuid.uuid4().hex[:8]}"

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Tạo user quản lý đào tạo
                cursor.execute(
                    """
                    INSERT INTO users (id, name, email, password_hash, role, status, created_at, updated_at)
                    VALUES (%s, 'Quản lý đào tạo Test', %s, 'hash', 'training_manager', 'active', NOW(), NOW())
                    """,
                    (cls.manager_user_id, f"mgr_{cls.manager_user_id}@test.ictu.edu.vn"),
                )
                cursor.execute(
                    "INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-training-manager', NOW())",
                    (cls.manager_user_id,),
                )

                # Tạo user giảng viên
                cursor.execute(
                    """
                    INSERT INTO users (id, name, email, password_hash, role, status, created_at, updated_at)
                    VALUES (%s, 'Giảng viên Test 229', %s, 'hash', 'trainer', 'active', NOW(), NOW())
                    """,
                    (cls.instructor_user_id, f"ins_{cls.instructor_user_id}@test.ictu.edu.vn"),
                )
                cursor.execute(
                    "INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())",
                    (cls.instructor_user_id,),
                )

                # Tạo session cho manager trong auth_sessions
                cursor.execute(
                    """
                    INSERT INTO auth_sessions (session_id, user_id, refresh_jti, created_at, last_activity_at, idle_expires_at, absolute_expires_at)
                    VALUES (%s, %s, %s, NOW(), NOW(), DATE_ADD(NOW(), INTERVAL 8 HOUR), DATE_ADD(NOW(), INTERVAL 8 HOUR))
                    """,
                    (cls.session_id, cls.manager_user_id, f"ref_{cls.session_id}"),
                )

                # Tạo lớp học với sĩ số max_capacity = 40 (để test cảnh báo sức chứa)
                cursor.execute(
                    """
                    INSERT INTO classes (id, class_code, program_id, max_capacity, status, created_at, updated_at)
                    VALUES (%s, %s, 'prog-mock', 40, 'in_progress', NOW(), NOW())
                    """,
                    (cls.class_id, cls.class_code),
                )

                # Khởi tạo 4 phòng trong danh mục chuẩn:
                # 1. Phòng vật lý sức chứa 30 (nhỏ hơn sĩ số 40 -> test cảnh báo sức chứa)
                cls.room_phy_small = Classroom(
                    id=f"room_phy_s_{uuid.uuid4().hex[:8]}",
                    room_code=f"P30_SMALL_{uuid.uuid4().hex[:4]}",
                    room_name="Phòng Học Nhỏ 30 Chỗ",
                    room_type="physical",
                    capacity=30,
                    status="active",
                )
                classroom_repository.insert_classroom(cls.room_phy_small)

                # 2. Phòng vật lý sức chứa 50 (đủ sức chứa)
                cls.room_phy_large = Classroom(
                    id=f"room_phy_l_{uuid.uuid4().hex[:8]}",
                    room_code=f"P50_LARGE_{uuid.uuid4().hex[:4]}",
                    room_name="Hội Trường Lớn 50 Chỗ",
                    room_type="physical",
                    capacity=50,
                    status="active",
                )
                classroom_repository.insert_classroom(cls.room_phy_large)

                # 3. Phòng trực tuyến
                cls.room_online = Classroom(
                    id=f"room_onl_{uuid.uuid4().hex[:8]}",
                    room_code=f"ONL_{uuid.uuid4().hex[:4]}",
                    room_name="Google Meet Kỹ Thuật",
                    room_type="online",
                    online_link="https://meet.google.com/ictu-online-test-229",
                    status="active",
                )
                classroom_repository.insert_classroom(cls.room_online)

                # 4. Phòng bảo trì / không khả dụng (status != active)
                cls.room_maintenance = Classroom(
                    id=f"room_maint_{uuid.uuid4().hex[:8]}",
                    room_code=f"MAINT_{uuid.uuid4().hex[:4]}",
                    room_name="Phòng Đang Bảo Trì",
                    room_type="physical",
                    capacity=40,
                    status="maintenance",
                )
                classroom_repository.insert_classroom(cls.room_maintenance)

                conn.commit()
        finally:
            conn.close()

        with cls.app.app_context():
            cls.token = create_access_token(
                identity=cls.manager_user_id,
                additional_claims={"sid": cls.session_id, "roles": ["training_manager"]},
            )
        cls.headers = {
            "Authorization": f"Bearer {cls.token}",
            "Content-Type": "application/json",
        }

    @classmethod
    def tearDownClass(cls):
        cls.clean_db()

    @classmethod
    def clean_db(cls):
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM class_schedules WHERE class_id LIKE 'cls_229_%'")
                cursor.execute("DELETE FROM classes WHERE id LIKE 'cls_229_%'")
                cursor.execute("DELETE FROM classrooms WHERE id LIKE 'room_%' OR room_code LIKE 'P30_SMALL_%' OR room_code LIKE 'P50_LARGE_%' OR room_code LIKE 'ONL_%' OR room_code LIKE 'MAINT_%'")
                cursor.execute("DELETE FROM user_roles WHERE user_id LIKE 'u_%_229_%'")
                cursor.execute("DELETE FROM auth_sessions WHERE user_id LIKE 'u_%_229_%'")
                cursor.execute("DELETE FROM users WHERE id LIKE 'u_%_229_%'")
                conn.commit()
        finally:
            conn.close()

    def test_01_update_schedule_with_physical_room_capacity_warning(self):
        """TC-229-01: Gán phòng vật lý nhỏ hơn sĩ số lớp -> Cập nhật thành công và trả về capacity_warning."""
        # Tạo 1 buổi học
        sch = ClassSchedule(
            id=f"sch_229_01_{uuid.uuid4().hex[:6]}",
            class_id=self.class_id,
            session_number=1,
            topic="Buổi 1: Test Phòng Nhỏ",
            learning_date="2026-11-10",
            shift="shift_1",
            start_time="07:30:00",
            end_time="09:30:00",
            room_id=None,
            instructor_id=self.instructor_user_id,
            status="scheduled",
        )
        class_schedule_repository.insert_schedules_batch([sch])

        payload = {
            "room_id": self.room_phy_small.id,
            "learning_date": "2026-11-10",
            "shift": "shift_1",
        }
        res = self.client.put(
            f"/api/v1/classes/{self.class_id}/schedules/{sch.id}",
            json=payload,
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200, res.get_json())
        data = res.get_json()["data"]

        # Kiểm tra room_id chuẩn
        self.assertEqual(data["schedule"]["room_id"], self.room_phy_small.id)
        self.assertEqual(data["schedule"]["room_name"], self.room_phy_small.room_name)
        self.assertEqual(data["schedule"]["room_code"], self.room_phy_small.room_code)
        self.assertFalse(data["schedule"]["is_legacy_room"])

        # Cảnh báo sức chứa (Lớp 40 chỗ - Phòng 30 chỗ)
        self.assertIsNotNone(data.get("capacity_warning"))
        self.assertIn("vượt sức chứa", data["capacity_warning"])

    def test_02_update_schedule_with_online_room_retrieves_online_link(self):
        """TC-229-02: Gán phòng trực tuyến -> Tự động gắn online_link và is_online=True từ danh mục."""
        sch = ClassSchedule(
            id=f"sch_229_02_{uuid.uuid4().hex[:6]}",
            class_id=self.class_id,
            session_number=2,
            topic="Buổi 2: Test Phòng Online",
            learning_date="2026-11-11",
            shift="shift_2",
            start_time="09:45:00",
            end_time="11:45:00",
            room_id=None,
            instructor_id=self.instructor_user_id,
            status="scheduled",
        )
        class_schedule_repository.insert_schedules_batch([sch])

        payload = {
            "room_id": self.room_online.id,
            "learning_date": "2026-11-11",
            "shift": "shift_2",
        }
        res = self.client.put(
            f"/api/v1/classes/{self.class_id}/schedules/{sch.id}",
            json=payload,
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200, res.get_json())
        data = res.get_json()["data"]

        self.assertEqual(data["schedule"]["room_id"], self.room_online.id)
        self.assertTrue(data["schedule"]["is_online"])
        self.assertEqual(data["schedule"]["online_link"], self.room_online.online_link)
        self.assertEqual(data["schedule"]["online_url"], self.room_online.online_link)
        # Phòng online không bị cảnh báo sức chứa vật lý
        self.assertIsNone(data.get("capacity_warning"))

    def test_03_reject_nonexistent_and_inactive_room(self):
        """TC-229-03: Chặn gán phòng không tồn tại hoặc phòng đang bảo trì/khóa."""
        sch = ClassSchedule(
            id=f"sch_229_03_{uuid.uuid4().hex[:6]}",
            class_id=self.class_id,
            session_number=3,
            topic="Buổi 3: Test Phòng Lỗi",
            learning_date="2026-11-12",
            shift="shift_1",
            start_time="07:30:00",
            end_time="09:30:00",
            room_id=None,
            instructor_id=self.instructor_user_id,
            status="scheduled",
        )
        class_schedule_repository.insert_schedules_batch([sch])

        # 1. Phòng không tồn tại
        res1 = self.client.put(
            f"/api/v1/classes/{self.class_id}/schedules/{sch.id}",
            json={"room_id": "non-existent-room-uuid-xyz"},
            headers=self.headers,
        )
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json()["code"], "ROOM_NOT_FOUND")

        # 2. Phòng bảo trì (status != active)
        res2 = self.client.put(
            f"/api/v1/classes/{self.class_id}/schedules/{sch.id}",
            json={"room_id": self.room_maintenance.id},
            headers=self.headers,
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "ROOM_NOT_ACTIVE")

    def test_04_room_conflict_detection_excluding_current_session(self):
        """TC-229-04: Phát hiện trùng phòng với buổi khác cùng khung giờ, nhưng loại trừ chính buổi đang sửa."""
        # Buổi A đã chiếm phòng P50_LARGE vào ngày 2026-11-13 ca 1 (07:30 - 09:30)
        sch_a = ClassSchedule(
            id=f"sch_229_04a_{uuid.uuid4().hex[:6]}",
            class_id=self.class_id,
            session_number=4,
            topic="Buổi A",
            learning_date="2026-11-13",
            shift="shift_1",
            start_time="07:30:00",
            end_time="09:30:00",
            room_id=self.room_phy_large.id,
            instructor_id=self.instructor_user_id,
            status="scheduled",
        )
        # Buổi B đang ở phòng khác
        sch_b = ClassSchedule(
            id=f"sch_229_04b_{uuid.uuid4().hex[:6]}",
            class_id=self.class_id,
            session_number=5,
            topic="Buổi B",
            learning_date="2026-11-13",
            shift="shift_1",
            start_time="07:30:00",
            end_time="09:30:00",
            room_id=None,
            instructor_id=None,
            status="scheduled",
        )
        class_schedule_repository.insert_schedules_batch([sch_a, sch_b])

        # Sửa buổi A mà không đổi phòng/giờ -> KHÔNG bị coi là tự trùng chính mình
        res_self = self.client.put(
            f"/api/v1/classes/{self.class_id}/schedules/{sch_a.id}",
            json={"topic": "Buổi A cập nhật tiêu đề"},
            headers=self.headers,
        )
        self.assertEqual(res_self.status_code, 200)

        # Đổi phòng buổi B sang P50_LARGE vào cùng khung giờ -> BỊ CHẶN do trùng với buổi A
        res_conflict = self.client.put(
            f"/api/v1/classes/{self.class_id}/schedules/{sch_b.id}",
            json={"room_id": self.room_phy_large.id},
            headers=self.headers,
        )
        self.assertEqual(res_conflict.status_code, 409)
        self.assertEqual(res_conflict.get_json()["code"], "SCHEDULE_CONFLICT_DETECTED")
        conflicts = res_conflict.get_json().get("data", {}).get("conflicts", [])
        self.assertTrue(any(c["conflict_type"] == "room" for c in conflicts))

    def test_05_legacy_room_preservation_when_updating_other_fields(self):
        """TC-229-05: Buổi học lưu phòng cũ 'P301' (chưa có trong catalog):
        - Hiển thị đúng chuỗi cũ kèm cờ is_legacy_room=True.
        - Sửa trường khác (ngày, giờ, topic) mà không đổi phòng -> Giữ nguyên 'P301', không crash hay âm thầm xóa."""
        sch_legacy = ClassSchedule(
            id=f"sch_229_05_{uuid.uuid4().hex[:6]}",
            class_id=self.class_id,
            session_number=6,
            topic="Buổi 6: Dữ liệu phòng cũ P301",
            learning_date="2026-11-14",
            shift="shift_1",
            start_time="07:30:00",
            end_time="09:30:00",
            room_id="P301",  # Chuỗi legacy chưa có trong danh mục
            instructor_id=self.instructor_user_id,
            status="scheduled",
        )
        class_schedule_repository.insert_schedules_batch([sch_legacy])

        # Đọc chi tiết buổi học
        fetched = class_schedule_repository.get_schedule_by_id(sch_legacy.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.room_id, "P301")
        self.assertEqual(fetched.room_name, "P301")
        self.assertTrue(fetched.is_legacy_room)
        self.assertEqual(fetched.legacy_room_raw, "P301")

        # Người dùng sửa topic nhưng KHÔNG đổi phòng
        res = self.client.put(
            f"/api/v1/classes/{self.class_id}/schedules/{sch_legacy.id}",
            json={"topic": "Chủ đề mới sau cập nhật", "room_id": "P301"},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200, res.get_json())
        data = res.get_json()["data"]
        self.assertEqual(data["schedule"]["topic"], "Chủ đề mới sau cập nhật")
        self.assertEqual(data["schedule"]["room_id"], "P301")
        self.assertTrue(data["schedule"]["is_legacy_room"])

    def test_06_unassign_room_when_null_sent(self):
        """TC-229-06: Người dùng chủ động bỏ phòng ('Chưa xếp phòng' - gửi null) -> room_id thành None."""
        sch = ClassSchedule(
            id=f"sch_229_06_{uuid.uuid4().hex[:6]}",
            class_id=self.class_id,
            session_number=7,
            topic="Buổi 7: Bỏ phòng",
            learning_date="2026-11-15",
            shift="shift_1",
            start_time="07:30:00",
            end_time="09:30:00",
            room_id=self.room_phy_large.id,
            instructor_id=self.instructor_user_id,
            status="scheduled",
        )
        class_schedule_repository.insert_schedules_batch([sch])

        res = self.client.put(
            f"/api/v1/classes/{self.class_id}/schedules/{sch.id}",
            json={"room_id": None},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertIsNone(data["schedule"]["room_id"])
        self.assertIsNone(data["schedule"]["room_name"])
        self.assertFalse(data["schedule"]["is_legacy_room"])


if __name__ == "__main__":
    unittest.main()
