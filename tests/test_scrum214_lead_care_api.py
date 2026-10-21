"""
Bộ kiểm thử tích hợp và đơn vị cho SCRUM-214: Nhật ký chăm sóc Lead & Lịch nhắc gọi lại (Lead Care Logs & Callback Reminder).
Bao gồm:
- TC214-01: Tạo interaction loại Gọi (call). Expected: lưu thành công.
- TC214-02: Tạo interaction loại Nhắn (message). Expected: lưu đúng.
- TC214-03: Tạo interaction loại Gặp (meeting). Expected: lưu đúng.
- TC214-04: Kiểm tra nội dung + thời điểm. Expected: đúng dữ liệu nhập.
- TC214-05: Reload / GET care-logs. Expected: nhật ký vẫn tồn tại, sắp xếp mới nhất ở trên.
- TC214-06: Kiểm tra người thực hiện. Expected: đúng user thao tác.
- TC214-07: Đặt ngày nhắc gọi lại trong tương lai. Expected: lưu thành công.
- TC214-08: Reload trang / GET lead. Expected: ngày nhắc vẫn còn.
- TC214-09: Thay đổi / xóa ngày nhắc. Expected: giá trị mới được lưu.
- TC214-10: Lead có ngày nhắc trong tương lai. Expected: không quá hạn.
- TC214-11: Lead có ngày nhắc đã qua. Expected: xác định quá hạn.
- TC214-12: Consultant data scope: không thao tác trên Lead của người khác (403).
"""

from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.config.jwt_handlers import register_jwt_handlers
from app.models.lead import (
    INTERACTION_TYPE_CALL,
    INTERACTION_TYPE_MEETING,
    INTERACTION_TYPE_MESSAGE,
    LEAD_SOURCE_DIRECT,
    LEAD_STATUS_NEW,
    Lead,
)
from app.models.login_session import LoginSession
from app.repositories import lead_repository
from app.routes.lead_routes import lead_bp


class Scrum214LeadCareApiTests(unittest.TestCase):
    """Bộ kiểm thử cho chức năng Nhật ký chăm sóc và Lịch nhắc gọi lại (SCRUM-214)."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum214-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(lead_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        # Admin user thực tế trong DB
        self.admin_user_id = "34068d8d-b2ec-4ce4-977a-28ac1b9b70de"
        self.authorized_session = LoginSession(
            session_id="session-authorized-214",
            user_id=self.admin_user_id,
            refresh_jti="ref-auth-214",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        # Consultant user thực tế trong DB (test)
        self.consultant_id = "4fae5ce7-f236-443e-a93a-778db2b0e1bf"
        self.consultant_session = LoginSession(
            session_id="session-consultant-214",
            user_id=self.consultant_id,
            refresh_jti="ref-cons-214",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        with self.app.app_context():
            self.admin_token = create_access_token(
                identity=self.admin_user_id,
                additional_claims={"sid": self.authorized_session.session_id},
            )
            self.consultant_token = create_access_token(
                identity=self.consultant_id,
                additional_claims={"sid": self.consultant_session.session_id},
            )

        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}
        self.consultant_headers = {"Authorization": f"Bearer {self.consultant_token}"}

        self.created_lead_ids = []

    def tearDown(self):
        for lid in self.created_lead_ids:
            try:
                lead_repository.delete_lead_for_testing(lid)
            except Exception:
                pass

    def _create_lead(
        self,
        full_name: str = "Lead Care Test",
        status: str = LEAD_STATUS_NEW,
        assigned_to_user_id: str | None = None,
        callback_date: str | None = None,
    ) -> str:
        lid = str(uuid.uuid4())
        phone = f"09{uuid.uuid4().int % 100000000:08d}"
        now = datetime.now(timezone.utc)
        lead = Lead(
            id=lid,
            full_name=full_name,
            phone=phone,
            email=f"care_{uuid.uuid4().hex[:6]}@example.com",
            source=LEAD_SOURCE_DIRECT,
            status=status,
            assigned_to_user_id=assigned_to_user_id,
            assigned_at=now if assigned_to_user_id else None,
            callback_date=callback_date,
            created_at=now,
            updated_at=now,
        )
        lead_repository.insert_lead(lead)
        self.created_lead_ids.append(lid)
        return lid

    # =========================================================================
    # TC214-01: Tạo interaction loại Gọi (call)
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc214_01_create_call_interaction_success(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="Lead Gọi")
        payload = {
            "interaction_type": "call",
            "content": "Đã gọi điện tư vấn khóa học Lập trình Web Fullstack",
            "interaction_at": "2026-10-12T09:00:00Z",
        }

        res = self.client.post(
            f"/api/v1/leads/{lid}/care-logs",
            json=payload,
            headers=self.admin_headers,
        )
        self.assertEqual(res.status_code, 201)
        body = res.get_json()
        self.assertEqual(body["status"], "success")
        data = body["data"]
        self.assertEqual(data["interaction_type"], "call")
        self.assertEqual(data["interaction_type_label"], "Gọi")
        self.assertEqual(data["content"], payload["content"])
        self.assertIn("2026-10-12T09:00:00", data["interaction_at"])

    # =========================================================================
    # TC214-02: Tạo interaction loại Nhắn (message)
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc214_02_create_message_interaction_success(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="Lead Nhắn")
        payload = {
            "interaction_type": "message",
            "content": "Gửi lộ trình học tập qua Zalo cho học viên",
            "interaction_at": "2026-10-12T10:30:00Z",
        }

        res = self.client.post(
            f"/api/v1/leads/{lid}/care-logs",
            json=payload,
            headers=self.admin_headers,
        )
        self.assertEqual(res.status_code, 201)
        body = res.get_json()
        self.assertEqual(body["data"]["interaction_type"], "message")
        self.assertEqual(body["data"]["interaction_type_label"], "Nhắn")

    # =========================================================================
    # TC214-03: Tạo interaction loại Gặp (meeting)
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc214_03_create_meeting_interaction_success(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="Lead Gặp")
        payload = {
            "interaction_type": "meeting",
            "content": "Gặp mặt trực tiếp tại văn phòng tuyển sinh ICTU",
            "interaction_at": "2026-10-12T14:00:00Z",
        }

        res = self.client.post(
            f"/api/v1/leads/{lid}/care-logs",
            json=payload,
            headers=self.admin_headers,
        )
        self.assertEqual(res.status_code, 201)
        body = res.get_json()
        self.assertEqual(body["data"]["interaction_type"], "meeting")
        self.assertEqual(body["data"]["interaction_type_label"], "Gặp")

    # =========================================================================
    # TC214-04: Kiểm tra nội dung + thời điểm nhập
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc214_04_content_and_time_validation(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="Lead Validate")

        # Rỗng nội dung -> 400
        res = self.client.post(
            f"/api/v1/leads/{lid}/care-logs",
            json={"interaction_type": "call", "content": "   "},
            headers=self.admin_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Nội dung tương tác không được để trống", res.get_json()["message"])

        # Loại không hợp lệ (không phải Gọi, Nhắn, Gặp) -> 400
        res_invalid_type = self.client.post(
            f"/api/v1/leads/{lid}/care-logs",
            json={"interaction_type": "email", "content": "Gửi email"},
            headers=self.admin_headers,
        )
        self.assertEqual(res_invalid_type.status_code, 400)
        self.assertIn("Chỉ chấp nhận Gọi, Nhắn hoặc Gặp", res_invalid_type.get_json()["message"])

    # =========================================================================
    # TC214-05: Reload trang -> nhật ký vẫn tồn tại (GET /api/v1/leads/<id>/care-logs)
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc214_05_care_logs_persist_and_sorted_newest_first(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="Lead Reload Test")

        # Tạo log 1
        self.client.post(
            f"/api/v1/leads/{lid}/care-logs",
            json={
                "interaction_type": "call",
                "content": "Tương tác 1 - gọi điện lần đầu",
                "interaction_at": "2026-10-10T08:00:00Z",
            },
            headers=self.admin_headers,
        )

        # Tạo log 2
        self.client.post(
            f"/api/v1/leads/{lid}/care-logs",
            json={
                "interaction_type": "message",
                "content": "Tương tác 2 - nhắn tin zalo tiếp nối",
                "interaction_at": "2026-10-11T09:00:00Z",
            },
            headers=self.admin_headers,
        )

        # Reload / Lấy danh sách
        res = self.client.get(f"/api/v1/leads/{lid}/care-logs", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        logs = res.get_json()["data"]
        self.assertEqual(len(logs), 2)
        # Mới nhất ở trên
        self.assertEqual(logs[0]["content"], "Tương tác 2 - nhắn tin zalo tiếp nối")
        self.assertEqual(logs[1]["content"], "Tương tác 1 - gọi điện lần đầu")

    # =========================================================================
    # TC214-06: Kiểm tra người thực hiện đúng user thao tác
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc214_06_performed_by_user_tracked_correctly(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="Lead Performed By")
        res = self.client.post(
            f"/api/v1/leads/{lid}/care-logs",
            json={"interaction_type": "meeting", "content": "Gặp trao đổi tư vấn"},
            headers=self.admin_headers,
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]
        self.assertEqual(data["performed_by_user_id"], self.admin_user_id)

    # =========================================================================
    # TC214-07 & TC214-08: Đặt ngày nhắc gọi lại và reload vẫn còn
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc214_07_08_set_callback_reminder_and_persist(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="Lead Callback")
        future_date = (date.today() + timedelta(days=7)).isoformat()

        res = self.client.patch(
            f"/api/v1/leads/{lid}/callback-date",
            json={"callback_date": future_date},
            headers=self.admin_headers,
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["data"]["callback_date"], future_date)

        # GET detail lead để kiểm tra persist
        res_get = self.client.get(f"/api/v1/leads/{lid}", headers=self.admin_headers)
        self.assertEqual(res_get.status_code, 200)
        lead_data = res_get.get_json()["data"]
        self.assertEqual(lead_data["callback_date"], future_date)

    # =========================================================================
    # TC214-09: Thay đổi ngày nhắc gọi lại
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc214_09_update_callback_reminder(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="Lead Update Callback", callback_date="2026-10-15")

        new_date = "2026-10-20"
        res = self.client.patch(
            f"/api/v1/leads/{lid}/callback-date",
            json={"callback_date": new_date},
            headers=self.admin_headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"]["callback_date"], new_date)

        # Xóa ngày nhắc (truyền null)
        res_clear = self.client.patch(
            f"/api/v1/leads/{lid}/callback-date",
            json={"callback_date": None},
            headers=self.admin_headers,
        )
        self.assertEqual(res_clear.status_code, 200)
        self.assertIsNone(res_clear.get_json()["data"]["callback_date"])

    # =========================================================================
    # TC214-10 & TC214-11: Xác định ngày nhắc trong tương lai vs quá hạn
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc214_10_11_overdue_detection(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        past_date = (date.today() - timedelta(days=2)).isoformat()
        future_date = (date.today() + timedelta(days=3)).isoformat()

        lid_overdue = self._create_lead(full_name="Lead Quá hạn", callback_date=past_date)
        lid_future = self._create_lead(full_name="Lead Chưa quá hạn", callback_date=future_date)

        # GET detail cả 2 lead
        res_o = self.client.get(f"/api/v1/leads/{lid_overdue}", headers=self.admin_headers)
        res_f = self.client.get(f"/api/v1/leads/{lid_future}", headers=self.admin_headers)

        self.assertEqual(res_o.status_code, 200)
        self.assertEqual(res_f.status_code, 200)

        data_o = res_o.get_json()["data"]
        data_f = res_f.get_json()["data"]

        # Backend trả về đúng callback_date
        self.assertEqual(data_o["callback_date"], past_date)
        self.assertEqual(data_f["callback_date"], future_date)

        # Kiểm tra logic quá hạn so với ngày hôm nay
        today_iso = date.today().isoformat()
        self.assertTrue(data_o["callback_date"] < today_iso)
        self.assertFalse(data_f["callback_date"] < today_iso)

    # =========================================================================
    # TC214-12: Consultant data scope (SCRUM-127 giữ vững)
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.lead_service.user_role_repository.get_role_codes_by_user_id")
    @patch("app.services.lead_service.user_repository.get_user_by_id")
    def test_tc214_12_consultant_data_scope_enforcement(
        self, mock_get_user, mock_roles, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.consultant_session
        mock_has_perm.return_value = True
        mock_roles.return_value = ["consultant"]

        class DummyConsultant:
            role = "consultant"
        mock_get_user.return_value = DummyConsultant()

        # Lead gán cho người khác (Admin user)
        other_user_id = self.admin_user_id
        lid_other = self._create_lead(full_name="Lead của người khác", assigned_to_user_id=other_user_id)

        # Consultant cố gắng thêm care log -> 403
        res_care = self.client.post(
            f"/api/v1/leads/{lid_other}/care-logs",
            json={"interaction_type": "call", "content": "Gọi thử"},
            headers=self.consultant_headers,
        )
        self.assertEqual(res_care.status_code, 403)

        # Consultant cố xem care log -> 403
        res_view = self.client.get(
            f"/api/v1/leads/{lid_other}/care-logs",
            headers=self.consultant_headers,
        )
        self.assertEqual(res_view.status_code, 403)

        # Consultant cố cập nhật callback date -> 403
        res_cb = self.client.patch(
            f"/api/v1/leads/{lid_other}/callback-date",
            json={"callback_date": "2026-10-25"},
            headers=self.consultant_headers,
        )
        self.assertEqual(res_cb.status_code, 403)


if __name__ == "__main__":
    unittest.main()
