"""
Test suite cho SCRUM-221: Quản lý phòng học và liên kết trực tuyến (TC221-01 -> TC221-08).
- Sub-task 221-01: Khai báo phòng vật lý / trực tuyến (TC221-01 -> TC221-04).
- Sub-task 221-02: Cảnh báo khi sĩ số lớp vượt sức chứa phòng (TC221-05 -> TC221-08).
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid
from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.database.ensure_business_roles import ensure_business_roles
from app.main import app
from app.models.login_session import LoginSession
from app.repositories import classroom_repository


class Scrum221ClassroomManagementApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_business_roles()

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.admin_user_id = "34068d8d-b2ec-4ce4-977a-28ac1b9b70de"
        self.now = datetime.now(timezone.utc)

        # Mock session cho Quản lý đào tạo (admin/training_manager)
        self.session_id = f"test-session-{uuid.uuid4()}"
        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.admin_user_id,
            refresh_jti=f"ref-{self.session_id}",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(hours=8),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.session_patcher = patch("app.utils.rbac_auth.get_session_by_id", return_value=self.session)
        self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)

        with self.app.app_context():
            self.admin_token = create_access_token(
                identity=self.admin_user_id,
                additional_claims={
                    "roles": ["admin", "training_manager"],
                    "sid": self.session_id,
                },
            )

        self.created_room_ids = []

    def tearDown(self):
        for rid in self.created_room_ids:
            try:
                classroom_repository.delete_classroom_for_testing(rid)
            except Exception:
                pass

    # =========================================================================
    # 221-01: KHAI BÁO PHÒNG VẬT LÝ / TRỰC TUYẾN (TC221-01 -> TC221-04)
    # =========================================================================

    def test_tc221_01_create_physical_room(self):
        """TC221-01: Tạo phòng vật lý -> capacity lưu đúng (> 0)."""
        room_code = f"ROOM-PHY-{uuid.uuid4().hex[:6].upper()}"
        res = self.client.post(
            "/api/v1/rooms",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "room_code": room_code,
                "room_name": "Phòng thực hành máy tính 101",
                "room_type": "physical",
                "capacity": 35,
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]
        self.created_room_ids.append(data["id"])

        self.assertEqual(data["room_code"], room_code)
        self.assertEqual(data["room_type"], "physical")
        self.assertEqual(data["capacity"], 35)
        self.assertIsNone(data["online_link"])

    def test_tc221_02_reload_physical_room_persists(self):
        """TC221-02: Reload/GET lại phòng vật lý -> thông tin tồn tại và lưu đúng."""
        room_code = f"ROOM-PHY-{uuid.uuid4().hex[:6].upper()}"
        res = self.client.post(
            "/api/v1/rooms",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "room_code": room_code,
                "room_name": "Phòng lý thuyết A2-201",
                "room_type": "physical",
                "capacity": 50,
            },
        )
        self.assertEqual(res.status_code, 201)
        room_id = res.get_json()["data"]["id"]
        self.created_room_ids.append(room_id)

        # GET lại chi tiết
        get_res = self.client.get(
            f"/api/v1/rooms/{room_id}",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(get_res.status_code, 200)
        data = get_res.get_json()["data"]
        self.assertEqual(data["id"], room_id)
        self.assertEqual(data["room_code"], room_code)
        self.assertEqual(data["capacity"], 50)
        self.assertEqual(data["room_type"], "physical")

    def test_tc221_03_create_online_room(self):
        """TC221-03: Tạo phòng trực tuyến với link liên kết -> lưu thành công."""
        room_code = f"ROOM-ONL-{uuid.uuid4().hex[:6].upper()}"
        online_link = "https://meet.google.com/xyz-abcd-uvw"
        res = self.client.post(
            "/api/v1/rooms",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "room_code": room_code,
                "room_name": "Phòng học trực tuyến Google Meet 01",
                "room_type": "online",
                "online_link": online_link,
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]
        self.created_room_ids.append(data["id"])

        self.assertEqual(data["room_code"], room_code)
        self.assertEqual(data["room_type"], "online")
        self.assertEqual(data["online_link"], online_link)
        self.assertIsNone(data["capacity"])

    def test_tc221_04_reload_online_room_persists(self):
        """TC221-04: Reload/GET lại phòng trực tuyến -> link persist đúng."""
        room_code = f"ROOM-ONL-{uuid.uuid4().hex[:6].upper()}"
        online_link = "https://zoom.us/j/9876543210"
        res = self.client.post(
            "/api/v1/rooms",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "room_code": room_code,
                "room_name": "Phòng Zoom Hội thảo 02",
                "room_type": "online",
                "online_link": online_link,
            },
        )
        self.assertEqual(res.status_code, 201)
        room_id = res.get_json()["data"]["id"]
        self.created_room_ids.append(room_id)

        get_res = self.client.get(
            f"/api/v1/rooms/{room_id}",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(get_res.status_code, 200)
        data = get_res.get_json()["data"]
        self.assertEqual(data["id"], room_id)
        self.assertEqual(data["online_link"], online_link)
        self.assertEqual(data["room_type"], "online")
        self.assertIsNone(data["capacity"])

    # 221-02 tests will be activated in sub-task 221-02
    pass


if __name__ == "__main__":
    unittest.main()
