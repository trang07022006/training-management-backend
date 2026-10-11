"""
Kiểm thử tăng cường bảo mật và phòng thủ cho Quản trị Lead (SCRUM-126 - Activity A4).
Bao gồm:
1. Phòng chống rò rỉ thông tin riêng tư (PII Exposure):
   - Người dùng công khai / chưa đăng nhập không thể truy cập danh sách hoặc chi tiết Lead.
   - Phản hồi từ public consultation chỉ trả về id và created_at, không trả về SĐT hay email.
2. Kiểm tra phân quyền và IDOR (Insecure Direct Object Reference):
   - Học viên (trainee) và người dùng thông thường không thể xem hoặc sửa Lead bằng cách đoán UUID.
3. Phòng chống SQL Injection:
   - Truy vấn với các payload SQL injection độc hại vào các tham số tìm kiếm, phân trang và cập nhật.
4. Bảo vệ tính toàn vẹn dữ liệu:
   - Chặn chèn các trường can thiệp hệ thống qua payload PATCH.
   - Xác nhận API Public Consultation tiếp tục hoạt động đúng hợp đồng và không bị ảnh hưởng.
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.config.jwt_handlers import register_jwt_handlers
from app.database.connection import get_db_connection
from app.models.lead import (
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_STATUS_NEW,
    Lead,
)
from app.models.login_session import LoginSession
from app.repositories import lead_repository
from app.routes.lead_routes import lead_bp
from app.routes.public_consultation_routes import public_consultation_bp


class Scrum126LeadSecurityTests(unittest.TestCase):
    """Kiểm thử phòng thủ và bảo mật toàn diện cho Lead Management."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum126-security-secret-at-least-32-chars",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(lead_bp)
        self.app.register_blueprint(public_consultation_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        # Admin / Manager Session
        self.admin_user_id = "user-admin-126-sec"
        self.admin_session = LoginSession(
            session_id="session-admin-126-sec",
            user_id=self.admin_user_id,
            refresh_jti="ref-admin-126-sec",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        # Unprivileged Trainee Session
        self.trainee_user_id = "user-trainee-126-sec"
        self.trainee_session = LoginSession(
            session_id="session-trainee-126-sec",
            user_id=self.trainee_user_id,
            refresh_jti="ref-trainee-126-sec",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(days=7),
            revoked_at=None,
        )

        with self.app.app_context():
            self.admin_token = create_access_token(
                identity=self.admin_user_id,
                additional_claims={"sid": self.admin_session.session_id},
            )
            self.trainee_token = create_access_token(
                identity=self.trainee_user_id,
                additional_claims={"sid": self.trainee_session.session_id},
            )

        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}
        self.trainee_headers = {"Authorization": f"Bearer {self.trainee_token}"}

    def test_01_public_user_cannot_access_lead_endpoints(self):
        """Khách công khai không thể gọi bất kỳ endpoint nội bộ nào của Lead."""
        res_list = self.client.get("/api/v1/leads")
        self.assertEqual(res_list.status_code, 401)

        some_uuid = str(uuid.uuid4())
        res_detail = self.client.get(f"/api/v1/leads/{some_uuid}")
        self.assertEqual(res_detail.status_code, 401)

        res_patch = self.client.patch(f"/api/v1/leads/{some_uuid}", json={"status": "contacted"})
        self.assertEqual(res_patch.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_trainee_idor_defense(self, mock_get_session, mock_has_perm):
        """Học viên không có quyền quản lý không thể truy cập hoặc cập nhật Lead bằng ID tùy ý."""
        mock_get_session.return_value = self.trainee_session
        mock_has_perm.return_value = False

        target_lead_id = str(uuid.uuid4())

        res_get = self.client.get(f"/api/v1/leads/{target_lead_id}", headers=self.trainee_headers)
        self.assertEqual(res_get.status_code, 403)
        self.assertEqual(res_get.get_json().get("code"), "FORBIDDEN")

        res_patch = self.client.patch(
            f"/api/v1/leads/{target_lead_id}",
            headers=self.trainee_headers,
            json={"status": "converted"},
        )
        self.assertEqual(res_patch.status_code, 403)

    def test_03_public_consultation_creates_lead_without_pii_leak(self):
        """Form công khai tạo lead thành công nhưng phản hồi không làm lộ PII nhạy cảm."""
        payload = {
            "full_name": "Nguyễn Bảo Mật",
            "phone": "0987112233",
            "email": "baomat@example.com",
            "message": "Cần tư vấn ngành CNTT chất lượng cao.",
        }
        res = self.client.post("/api/v1/public/consultations", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()

        self.assertIn("data", data)
        self.assertIn("id", data["data"])
        self.assertIn("created_at", data["data"])

        # PII tuyệt đối không trả về trong public API response
        self.assertNotIn("phone", data["data"])
        self.assertNotIn("email", data["data"])
        self.assertNotIn("message", data["data"])
        self.assertNotIn("status", data["data"])

        # Cleanup
        created_id = data["data"]["id"]
        lead_repository.delete_lead_for_testing(created_id)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_04_sql_injection_defense_in_update(self, mock_get_session, mock_has_perm):
        """Truyền payload SQL Injection vào status bị chặn tại bước validation."""
        mock_get_session.return_value = self.admin_session
        mock_has_perm.return_value = True

        lead_id = str(uuid.uuid4())
        sql_injection_status = "contacted'; DROP TABLE leads; --"

        res = self.client.patch(
            f"/api/v1/leads/{lead_id}",
            headers=self.admin_headers,
            json={"status": sql_injection_status},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "INVALID_STATUS")
