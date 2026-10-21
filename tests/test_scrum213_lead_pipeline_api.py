"""
Bộ kiểm thử tích hợp và đơn vị cho SCRUM-213: Bảng phễu Lead (Pipeline / Kanban) và Lịch sử trạng thái.
Bao gồm:
1. Chuẩn hóa 6 trạng thái nghiệp vụ và thứ tự hiển thị (TC213-01).
2. API lấy dữ liệu bảng phễu (/api/v1/leads/pipeline) kèm số lượng chính xác từng cột (TC213-02).
3. Cập nhật trạng thái và lưu DB sau reload (TC213-03).
4. Ghi nhận lịch sử vào bảng lead_status_history khi trạng thái thay đổi (TC213-04).
5. Hiển thị thông tin lịch sử: old -> new, người thực hiện, thời gian (TC213-05).
6. Chuyển sang Từ chối không chọn lý do -> 400 REJECTION_REASON_REQUIRED (TC213-06).
7. Hủy từ chối / no-op: Lead giữ trạng thái cũ, không tạo history giả (TC213-07).
8. Chọn lý do từ chối hợp lệ và confirm -> lưu status, reason, history (TC213-08).
9. Phân quyền Tư vấn tuyển sinh (Consultant scope) trên pipeline và history (TC213-09).
10. Regression List view: Tìm kiếm/lọc vẫn hoạt động bình thường (TC213-10).
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.config.jwt_handlers import register_jwt_handlers
from app.models.lead import (
    LEAD_SOURCE_DIRECT,
    LEAD_STATUS_CONSULTING,
    LEAD_STATUS_CONTACTED,
    LEAD_STATUS_NEW,
    LEAD_STATUS_REJECTED,
    LEAD_STATUS_TRIAL_SCHEDULED,
    LEAD_STATUS_WON,
    REJECTION_REASON_COST_UNSUITABLE,
    REJECTION_REASON_NO_NEED,
    REJECTION_REASON_OTHER,
    Lead,
)
from app.models.login_session import LoginSession
from app.repositories import lead_repository
from app.routes.lead_routes import lead_bp


class Scrum213LeadPipelineApiTests(unittest.TestCase):
    """Bộ kiểm thử cho chức năng Bảng phễu Lead và Lịch sử trạng thái (SCRUM-213)."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum213-at-least-32-bytes-long",
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
            session_id="session-authorized-213",
            user_id=self.admin_user_id,
            refresh_jti="ref-auth-213",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        # Consultant user thực tế trong DB (test)
        self.consultant_id = "4fae5ce7-f236-443e-a93a-778db2b0e1bf"
        self.consultant_session = LoginSession(
            session_id="session-consultant-213",
            user_id=self.consultant_id,
            refresh_jti="ref-cons-213",
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
        full_name: str = "Lead QA Test",
        status: str = LEAD_STATUS_NEW,
        assigned_to_user_id: str | None = None,
        rejection_reason: str | None = None,
    ) -> str:
        lid = str(uuid.uuid4())
        phone = f"09{uuid.uuid4().int % 100000000:08d}"
        now = datetime.now(timezone.utc)
        lead = Lead(
            id=lid,
            full_name=full_name,
            phone=phone,
            email=f"qa_{uuid.uuid4().hex[:6]}@example.com",
            source=LEAD_SOURCE_DIRECT,
            status=status,
            rejection_reason=rejection_reason,
            assigned_to_user_id=assigned_to_user_id,
            assigned_at=now if assigned_to_user_id else None,
            created_at=now,
            updated_at=now,
        )
        lead_repository.insert_lead(lead)
        self.created_lead_ids.append(lid)
        return lid

    # =========================================================================
    # TC213-01: Hiển thị đủ 6 cột đúng thứ tự
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc213_01_pipeline_six_columns_exact_order(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.get("/api/v1/leads/pipeline", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "success")

        columns = body["data"]["columns"]
        self.assertEqual(len(columns), 6)

        expected = [
            ("new", "Mới"),
            ("contacted", "Đã liên hệ"),
            ("consulting", "Đang tư vấn"),
            ("trial_scheduled", "Hẹn học thử"),
            ("won", "Chốt"),
            ("rejected", "Từ chối"),
        ]
        for idx, (code, label) in enumerate(expected):
            self.assertEqual(columns[idx]["status"], code)
            self.assertEqual(columns[idx]["label"], label)
            self.assertIsInstance(columns[idx]["count"], int)
            self.assertIsInstance(columns[idx]["leads"], list)
            self.assertEqual(columns[idx]["count"], len(columns[idx]["leads"]))

    # =========================================================================
    # TC213-02: Mỗi cột hiển thị đúng số lượng count dựa trên dữ liệu thật
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc213_02_pipeline_counts_accuracy(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid_a = self._create_lead(full_name="QA-S213-A", status=LEAD_STATUS_NEW)
        lid_b = self._create_lead(full_name="QA-S213-B", status=LEAD_STATUS_CONTACTED)
        lid_c = self._create_lead(full_name="QA-S213-C", status=LEAD_STATUS_CONSULTING)
        lid_d = self._create_lead(full_name="QA-S213-D", status=LEAD_STATUS_TRIAL_SCHEDULED)
        lid_e = self._create_lead(full_name="QA-S213-E", status=LEAD_STATUS_WON)
        lid_f = self._create_lead(
            full_name="QA-S213-F",
            status=LEAD_STATUS_REJECTED,
            rejection_reason=REJECTION_REASON_NO_NEED,
        )

        res = self.client.get("/api/v1/leads/pipeline", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        new_col = next(c for c in data["columns"] if c["status"] == "new")
        contacted_col = next(c for c in data["columns"] if c["status"] == "contacted")
        consulting_col = next(c for c in data["columns"] if c["status"] == "consulting")
        trial_col = next(c for c in data["columns"] if c["status"] == "trial_scheduled")
        won_col = next(c for c in data["columns"] if c["status"] == "won")
        rejected_col = next(c for c in data["columns"] if c["status"] == "rejected")

        self.assertTrue(any(l["id"] == lid_a for l in new_col["leads"]))
        self.assertTrue(any(l["id"] == lid_b for l in contacted_col["leads"]))
        self.assertTrue(any(l["id"] == lid_c for l in consulting_col["leads"]))
        self.assertTrue(any(l["id"] == lid_d for l in trial_col["leads"]))
        self.assertTrue(any(l["id"] == lid_e for l in won_col["leads"]))
        self.assertTrue(any(l["id"] == lid_f for l in rejected_col["leads"]))

    # =========================================================================
    # TC213-03: Drag Mới -> Đã liên hệ, reload vẫn giữ status
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc213_03_drag_new_to_contacted_persists_after_reload(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="QA-S213-DragA", status=LEAD_STATUS_NEW)

        # Cập nhật status
        patch_res = self.client.patch(
            f"/api/v1/leads/{lid}",
            headers=self.admin_headers,
            json={"status": LEAD_STATUS_CONTACTED},
        )
        self.assertEqual(patch_res.status_code, 200)

        # GET reload để kiểm tra lưu status thật
        get_res = self.client.get(f"/api/v1/leads/{lid}", headers=self.admin_headers)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.get_json()["data"]["status"], LEAD_STATUS_CONTACTED)

    # =========================================================================
    # TC213-04 & TC213-05: Đổi trạng thái ghi lịch sử, thông tin đầy đủ
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc213_04_05_status_history_logging_and_display(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="QA-S213-History", status=LEAD_STATUS_CONTACTED)

        # Đổi status sang consulting
        patch_res = self.client.patch(
            f"/api/v1/leads/{lid}",
            headers=self.admin_headers,
            json={"status": LEAD_STATUS_CONSULTING},
        )
        self.assertEqual(patch_res.status_code, 200)

        # Xem lịch sử
        hist_res = self.client.get(f"/api/v1/leads/{lid}/status-history", headers=self.admin_headers)
        self.assertEqual(hist_res.status_code, 200)
        history_list = hist_res.get_json()["data"]
        self.assertGreaterEqual(len(history_list), 1)

        latest = history_list[0]
        self.assertEqual(latest["old_status"], "contacted")
        self.assertEqual(latest["new_status"], "consulting")
        self.assertEqual(latest["performed_by_user_id"], self.admin_user_id)
        self.assertIsNotNone(latest["performed_by_name"])
        self.assertIsNotNone(latest["created_at"])

    # =========================================================================
    # TC213-06: Chuyển sang Từ chối không chọn lý do bị từ chối
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc213_06_rejection_without_reason_rejected(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="QA-S213-RejectNoReason", status=LEAD_STATUS_NEW)

        patch_res = self.client.patch(
            f"/api/v1/leads/{lid}",
            headers=self.admin_headers,
            json={"status": LEAD_STATUS_REJECTED},
        )
        self.assertEqual(patch_res.status_code, 400)
        self.assertEqual(patch_res.get_json()["code"], "REJECTION_REASON_REQUIRED")

        # Đảm bảo status chưa đổi
        lead = lead_repository.get_lead_by_id(lid)
        self.assertEqual(lead.status, LEAD_STATUS_NEW)

    # =========================================================================
    # TC213-07: Hủy từ chối / cùng status không tạo lịch sử
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc213_07_no_history_on_same_status_or_cancel(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="QA-S213-Cancel", status=LEAD_STATUS_NEW)

        hist_count_before = len(lead_repository.get_lead_status_history(lid))

        # Gửi cùng status "new"
        patch_res = self.client.patch(
            f"/api/v1/leads/{lid}",
            headers=self.admin_headers,
            json={"status": LEAD_STATUS_NEW},
        )
        self.assertEqual(patch_res.status_code, 200)

        hist_count_after = len(lead_repository.get_lead_status_history(lid))
        self.assertEqual(hist_count_before, hist_count_after)

    # =========================================================================
    # TC213-08: Chọn lý do từ chối và confirm thành công
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc213_08_rejection_with_reason_success(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="QA-S213-RejectConfirm", status=LEAD_STATUS_CONSULTING)

        patch_res = self.client.patch(
            f"/api/v1/leads/{lid}",
            headers=self.admin_headers,
            json={
                "status": LEAD_STATUS_REJECTED,
                "reason": REJECTION_REASON_COST_UNSUITABLE,
                "notes": "Học phí cao hơn ngân sách dự kiến",
            },
        )
        self.assertEqual(patch_res.status_code, 200)
        data = patch_res.get_json()["data"]
        self.assertEqual(data["status"], LEAD_STATUS_REJECTED)
        self.assertEqual(data["rejection_reason"], REJECTION_REASON_COST_UNSUITABLE)

        # Kiểm tra history đã ghi reason và notes
        hist_res = self.client.get(f"/api/v1/leads/{lid}/status-history", headers=self.admin_headers)
        self.assertEqual(hist_res.status_code, 200)
        latest = hist_res.get_json()["data"][0]
        self.assertEqual(latest["old_status"], "consulting")
        self.assertEqual(latest["new_status"], "rejected")
        self.assertEqual(latest["reason"], REJECTION_REASON_COST_UNSUITABLE)
        self.assertEqual(latest["notes"], "Học phí cao hơn ngân sách dự kiến")

    # =========================================================================
    # TC213-09: Consultant login chỉ xem và sửa Lead của chính mình
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc213_09_consultant_scope_isolation(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.consultant_session
        mock_has_perm.return_value = True

        my_lid = self._create_lead(
            full_name="Consultant My Lead",
            status=LEAD_STATUS_NEW,
            assigned_to_user_id=self.consultant_id,
        )
        other_lid = self._create_lead(
            full_name="Other Lead",
            status=LEAD_STATUS_NEW,
            assigned_to_user_id=None,
        )

        # Consultant xem pipeline
        res = self.client.get("/api/v1/leads/pipeline", headers=self.consultant_headers)
        self.assertEqual(res.status_code, 200)
        all_ids = [l["id"] for l in res.get_json()["data"]["leads"]]
        self.assertIn(my_lid, all_ids)
        self.assertNotIn(other_lid, all_ids)

        # Consultant không được xem history của lead người khác
        forbid_hist = self.client.get(f"/api/v1/leads/{other_lid}/status-history", headers=self.consultant_headers)
        self.assertEqual(forbid_hist.status_code, 403)

        # Consultant không được update lead của người khác
        forbid_patch = self.client.patch(
            f"/api/v1/leads/{other_lid}",
            headers=self.consultant_headers,
            json={"status": LEAD_STATUS_CONTACTED},
        )
        self.assertEqual(forbid_patch.status_code, 403)

    # =========================================================================
    # TC213-10: Regression List view vẫn hoạt động bình thường
    # =========================================================================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_tc213_10_regression_list_view_and_filters(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        lid = self._create_lead(full_name="QA-S213-Regression", status=LEAD_STATUS_NEW)

        # List view với search và status filter
        res = self.client.get(f"/api/v1/leads?search=Regression&status=new", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]
        self.assertTrue(any(it["id"] == lid for it in items))
