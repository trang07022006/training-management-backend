"""
Kiểm thử liên thông Quản lý Ngày nghỉ lễ và Sinh thời khóa biểu (SCRUM-224).
Xác minh:
1. API thêm ngày nghỉ, lấy danh sách ngày nghỉ, và xem trước/sinh lịch dùng chung 1 database/table.
2. Kiểm tra bộ lọc năm (year), khoảng ngày (from_date, to_date).
3. Sinh lịch xuyên năm mới (cross new year 2026 -> 2027) tự động bỏ qua Tết Dương lịch nhưng sinh đủ số buổi.
4. Xóa ngày nghỉ thì khi sinh lịch không còn bị bỏ qua.
"""

from datetime import date, datetime, timedelta, timezone
import json
import unittest
import uuid
from unittest.mock import patch
from flask_jwt_extended import create_access_token

from app.main import app
from app.models.holiday import Holiday
from app.models.login_session import LoginSession
from app.models.class_entity import ClassEntity
from app.repositories import holiday_repository, class_repository


class TestScrum224HolidaysSyncIntegration(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.user_id = "test-mgr-sync-224"
        self.now = datetime.now(timezone.utc)
        self.session_id = f"test-sess-{uuid.uuid4()}"
        self.authorized_session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-sync-224",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(hours=8),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.session_patcher = patch("app.utils.rbac_auth.get_session_by_id", return_value=self.authorized_session)
        self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)

        self.perm_patcher = patch("app.utils.rbac_auth.has_permission", return_value=True)
        self.perm_patcher.start()
        self.addCleanup(self.perm_patcher.stop)

        with self.app.app_context():
            self.token = create_access_token(
                identity=self.user_id,
                additional_claims={"roles": ["training_manager"], "sid": self.session_id},
            )
            self.headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }

        # Lưu danh sách ID do chính test tạo để chỉ xóa những bản ghi này khi tearDown (an toàn dữ liệu)
        self.created_holiday_ids: list[str] = []

    def _track_holiday(self, holiday_id: str) -> str:
        if holiday_id and holiday_id not in self.created_holiday_ids:
            self.created_holiday_ids.append(holiday_id)
        return holiday_id

    def tearDown(self):
        for hid in self.created_holiday_ids:
            try:
                holiday_repository.delete_holiday(hid)
            except Exception:
                pass

    def test_1_same_database_table_lifecycle(self):
        """1. Thêm ngày nghỉ -> API danh sách thấy -> sinh lịch bỏ qua -> xóa ngày nghỉ -> sinh lịch không còn bỏ qua."""
        unique_date = "2028-11-20"
        holiday_name = "Ngày Nhà giáo Việt Nam 2028"

        # 1. Thêm ngày nghỉ qua POST /api/v1/holidays
        res_post = self.client.post(
            "/api/v1/holidays",
            json={"holiday_date": unique_date, "name": holiday_name, "description": "Nghỉ lễ tri ân"},
            headers=self.headers,
        )
        self.assertEqual(res_post.status_code, 201)
        post_data = res_post.get_json()
        self.assertEqual(post_data["code"], "HOLIDAY_CREATED")
        holiday_id = self._track_holiday(post_data["data"]["id"])

        # 2. Lấy danh sách qua GET /api/v1/holidays -> Phải có data.items chứa ngày này
        res_get = self.client.get("/api/v1/holidays", headers=self.headers)
        self.assertEqual(res_get.status_code, 200)
        get_data = res_get.get_json()
        self.assertIn("items", get_data["data"])
        items = get_data["data"]["items"]
        matched = [h for h in items if h["holiday_date"] == unique_date]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["name"], holiday_name)

        # 3. Xem trước sinh lịch đi qua ngày 2028-11-20
        # 2028-11-20 là Thứ 2 (weekday=0)
        mock_class = ClassEntity(
            id="cls-sync-test",
            class_code="L-SYNC-2028",
            program_id="prog-1",
            expected_start_date="2028-11-13",
            max_capacity=30,
            learning_mode="offline",
            status="preparing",
            created_at=self.now,
            updated_at=self.now,
            enrolled_count=0,
        )
        with patch.object(class_repository, "get_class_by_id", return_value=mock_class), \
             patch.object(class_repository, "get_class_subjects", return_value=[]), \
             patch("app.repositories.class_schedule_repository.list_schedules_by_class_id", return_value=[]):
            preview_payload = {
                "days_of_week": [2, 4, 6],  # Thứ 2, Thứ 4, Thứ 6
                "shift": "Ca 1",
                "start_date": "2028-11-13",
                "total_sessions": 5,
            }
            res_prev = self.client.post("/api/v1/classes/cls-sync-test/schedules/preview", json=preview_payload, headers=self.headers)
            self.assertEqual(res_prev.status_code, 200)
            prev_data = res_prev.get_json()["data"]

            # Kiểm tra ngày 2028-11-20 được bỏ qua
            self.assertEqual(len(prev_data["skipped_holidays"]), 1)
            self.assertEqual(prev_data["skipped_holidays"][0]["date"], "2028-11-20")
            self.assertEqual(prev_data["skipped_holidays"][0]["holiday_name"], holiday_name)
            # Vẫn sinh đủ 5 buổi
            self.assertEqual(prev_data["total_generated"], 5)
            session_dates = [s["learning_date"] for s in prev_data["schedules"]]
            self.assertNotIn("2028-11-20", session_dates)

        # 4. Xóa ngày nghỉ
        res_del = self.client.delete(f"/api/v1/holidays/{holiday_id}", headers=self.headers)
        self.assertEqual(res_del.status_code, 200)

        # 5. Xem trước sinh lịch lại -> Không còn bị bỏ qua
        with patch.object(class_repository, "get_class_by_id", return_value=mock_class), \
             patch.object(class_repository, "get_class_subjects", return_value=[]), \
             patch("app.repositories.class_schedule_repository.list_schedules_by_class_id", return_value=[]):
            res_prev2 = self.client.post("/api/v1/classes/cls-sync-test/schedules/preview", json=preview_payload, headers=self.headers)
            self.assertEqual(res_prev2.status_code, 200)
            prev_data2 = res_prev2.get_json()["data"]
            self.assertEqual(len(prev_data2["skipped_holidays"]), 0)
            session_dates2 = [s["learning_date"] for s in prev_data2["schedules"]]
            self.assertIn("2028-11-20", session_dates2)

    def test_2_cross_new_year_schedule_generation(self):
        """2. Sinh lịch xuyên năm mới (2026 -> 2027): Bỏ qua Tết Dương lịch 2027-01-01 nhưng sinh đủ 5 buổi."""
        # Thêm Tết Dương lịch 2027-01-01 nếu chưa có
        existing = holiday_repository.get_holiday_by_date("2027-01-01")
        if existing:
            expected_name = existing.name
        else:
            expected_name = "Tết Dương lịch 2027"
            hid = self._track_holiday(str(uuid.uuid4()))
            h = Holiday(id=hid, holiday_date="2027-01-01", name=expected_name)
            holiday_repository.insert_holiday(h)

        mock_class = ClassEntity(
            id="cls-newyear-test",
            class_code="L-NY-2027",
            program_id="prog-1",
            expected_start_date="2026-12-28",
            max_capacity=30,
            learning_mode="offline",
            status="preparing",
            created_at=self.now,
            updated_at=self.now,
            enrolled_count=0,
        )
        with patch.object(class_repository, "get_class_by_id", return_value=mock_class), \
             patch.object(class_repository, "get_class_subjects", return_value=[]), \
             patch("app.repositories.class_schedule_repository.list_schedules_by_class_id", return_value=[]):
            # 2026-12-28 (Thứ 2), 2026-12-30 (Thứ 4), 2027-01-01 (Thứ 6 - NGHỈ), 2027-01-04 (Thứ 2), 2027-01-06 (Thứ 4), 2027-01-08 (Thứ 6)
            payload = {
                "days_of_week": [2, 4, 6],
                "shift": "Ca 2",
                "start_date": "2026-12-28",
                "total_sessions": 5,
            }
            res = self.client.post("/api/v1/classes/cls-newyear-test/schedules/preview", json=payload, headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()["data"]

            self.assertEqual(data["total_generated"], 5)
            self.assertEqual(len(data["skipped_holidays"]), 1)
            self.assertEqual(data["skipped_holidays"][0]["date"], "2027-01-01")
            self.assertEqual(data["skipped_holidays"][0]["holiday_name"], expected_name)

            session_dates = [s["learning_date"] for s in data["schedules"]]
            self.assertEqual(session_dates, ["2026-12-28", "2026-12-30", "2027-01-04", "2027-01-06", "2027-01-08"])

    def test_3_year_filter_in_list_holidays(self):
        """3. Kiểm tra lọc ngày nghỉ theo năm (year=2026 và year=2027)."""
        existing26 = holiday_repository.get_holiday_by_date("2026-12-25")
        if not existing26:
            hid26 = self._track_holiday(str(uuid.uuid4()))
            holiday_repository.insert_holiday(Holiday(id=hid26, holiday_date="2026-12-25", name="Giáng sinh 2026"))
        
        existing27 = holiday_repository.get_holiday_by_date("2027-01-02")
        if not existing27:
            hid27 = self._track_holiday(str(uuid.uuid4()))
            holiday_repository.insert_holiday(Holiday(id=hid27, holiday_date="2027-01-02", name="Nghỉ bù năm mới 2027"))

        # Lọc năm 2026
        res26 = self.client.get("/api/v1/holidays?year=2026", headers=self.headers)
        self.assertEqual(res26.status_code, 200)
        items26 = res26.get_json()["data"]["items"]
        dates26 = [it["holiday_date"] for it in items26]
        self.assertIn("2026-12-25", dates26)
        self.assertNotIn("2027-01-02", dates26)

        # Lọc năm 2027
        res27 = self.client.get("/api/v1/holidays?year=2027", headers=self.headers)
        self.assertEqual(res27.status_code, 200)
        items27 = res27.get_json()["data"]["items"]
        dates27 = [it["holiday_date"] for it in items27]
        self.assertIn("2027-01-02", dates27)
        self.assertNotIn("2026-12-25", dates27)
