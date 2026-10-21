"""
Tests for SCRUM-224 - Sub-task 224-01: Quản lý ngày nghỉ lễ (Holidays Model & API).
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid
from flask_jwt_extended import create_access_token
from app.main import app
from app.models.holiday import Holiday
from app.models.login_session import LoginSession
from app.repositories import holiday_repository


class TestScrum224HolidaysApi(unittest.TestCase):
    """Kiểm thử API quản lý ngày nghỉ lễ (SCRUM-224 - 224-01)."""

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.user_id = "test-training-manager-224"
        self.now = datetime.now(timezone.utc)
        self.session_id = f"test-session-{uuid.uuid4()}"
        self.authorized_session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-auth-224",
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
            self.manager_token = create_access_token(
                identity=self.user_id,
                additional_claims={
                    "roles": ["training_manager"],
                    "sid": self.session_id,
                },
            )
            self.headers = {
                "Authorization": f"Bearer {self.manager_token}",
                "Content-Type": "application/json",
            }

        self.cleanup_dates = [
            "2029-01-01",
            "2029-04-30",
            "2029-05-01",
            "2029-09-01",
            "2029-09-02",
            "2029-12-25",
        ]
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        for d in self.cleanup_dates:
            existing = holiday_repository.get_holiday_by_date(d)
            if existing:
                holiday_repository.delete_holiday(existing.id)

    def test_tc224_01_create_holiday_success(self):
        """TC224-01: Khai báo ngày nghỉ lễ hợp lệ thành công."""
        unique_date = "2029-01-01"
        payload = {
            "holiday_date": unique_date,
            "name": "Tết Dương lịch 2029",
            "description": "Nghỉ lễ đầu năm mới",
        }
        res = self.client.post("/api/v1/holidays", json=payload, headers=self.headers)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["code"], "HOLIDAY_CREATED")
        self.assertEqual(data["data"]["holiday_date"], unique_date)
        self.assertEqual(data["data"]["name"], "Tết Dương lịch 2029")

    def test_tc224_02_duplicate_holiday_rejected(self):
        """TC224-02: Không cho phép trùng ngày nghỉ lễ trong hệ thống."""
        unique_date = "2029-04-30"
        h = Holiday(id=str(uuid.uuid4()), holiday_date=unique_date, name="Giải phóng miền Nam 2029")
        holiday_repository.insert_holiday(h)

        payload = {
            "holiday_date": unique_date,
            "name": "Tên khác nhưng trùng ngày",
        }
        res = self.client.post("/api/v1/holidays", json=payload, headers=self.headers)
        self.assertEqual(res.status_code, 409)
        data = res.get_json()
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["code"], "HOLIDAY_ALREADY_EXISTS")

    def test_tc224_03_create_holiday_validation_errors(self):
        """TC224-03: Kiểm tra tính hợp lệ dữ liệu (thiếu tên, định dạng ngày sai)."""
        # Thiếu tên
        res = self.client.post("/api/v1/holidays", json={"holiday_date": "2029-05-01", "name": "   "}, headers=self.headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "MISSING_NAME")

        # Định dạng ngày sai
        res = self.client.post("/api/v1/holidays", json={"holiday_date": "01-05-2029", "name": "Quốc tế lao động"}, headers=self.headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_DATE_FORMAT")

    def test_tc224_04_list_holidays(self):
        """TC224-04: Lấy danh sách ngày nghỉ lễ, sắp xếp theo ngày tăng dần."""
        h1_date = "2029-09-02"
        h2_date = "2029-09-01"

        h1 = Holiday(id=str(uuid.uuid4()), holiday_date=h1_date, name="Quốc khánh")
        h2 = Holiday(id=str(uuid.uuid4()), holiday_date=h2_date, name="Nghỉ trước Quốc khánh")
        holiday_repository.insert_holiday(h1)
        holiday_repository.insert_holiday(h2)

        res = self.client.get("/api/v1/holidays?from_date=2029-09-01&to_date=2029-09-02", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        items = data["data"]["items"]
        self.assertGreaterEqual(len(items), 2)
        dates = [it["holiday_date"] for it in items]
        self.assertEqual(dates, sorted(dates))

    def test_tc224_05_delete_holiday(self):
        """TC224-05: Xóa ngày nghỉ lễ theo ID."""
        h = Holiday(id=str(uuid.uuid4()), holiday_date="2029-12-25", name="Giáng sinh")
        holiday_repository.insert_holiday(h)

        res = self.client.delete(f"/api/v1/holidays/{h.id}", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["code"], "HOLIDAY_DELETED")

        self.assertIsNone(holiday_repository.get_holiday_by_id(h.id))
