"""
Test suite cho CHANGE REQUEST - SCRUM-215:
INITIAL PASSWORD + FORCE CHANGE ON FIRST LOGIN (TC-01 -> TC-09).
"""

import os
import unittest
import uuid
from unittest.mock import patch

from flask import json
from werkzeug.security import check_password_hash

from app.main import app
from app.database.connection import get_db_connection
from app.models.lead import Lead
from app.repositories import lead_repository, user_repository
from app.services import student_service
from app.services.student_service import StudentServiceError


class Scrum215InitialPasswordForceChangeTests(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.test_initial_password = "InitStudent@2026Pass"
        os.environ["STUDENT_INITIAL_PASSWORD"] = self.test_initial_password
        self.cleanup_lead_ids = []
        self.cleanup_user_ids = []
        self.cleanup_student_ids = []

    def tearDown(self):
        os.environ["STUDENT_INITIAL_PASSWORD"] = self.test_initial_password
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                for sid in self.cleanup_student_ids:
                    cursor.execute("DELETE FROM students WHERE id = %s", (sid,))
                for lid in self.cleanup_lead_ids:
                    cursor.execute("DELETE FROM students WHERE lead_id = %s", (lid,))
                    cursor.execute("DELETE FROM leads WHERE id = %s", (lid,))
                for uid in self.cleanup_user_ids:
                    cursor.execute("DELETE FROM students WHERE user_id = %s", (uid,))
                    cursor.execute("DELETE FROM user_roles WHERE user_id = %s", (uid,))
                    cursor.execute("DELETE FROM login_sessions WHERE user_id = %s", (uid,))
                    cursor.execute("DELETE FROM users WHERE id = %s", (uid,))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def _create_won_lead(self, email=None, phone=None):
        lead_id = str(uuid.uuid4())
        suffix = uuid.uuid4().hex[:6]
        test_email = email or f"lead.{suffix}@student.test.edu.vn"
        test_phone = phone or f"091{suffix[:7].zfill(7)}"
        lead = Lead(
            id=lead_id,
            full_name=f"Học Viên {suffix.upper()}",
            phone=test_phone,
            email=test_email,
            source="website",
            status="won",
            interested_program_id=None,
        )
        created = lead_repository.insert_lead(lead)
        self.cleanup_lead_ids.append(created.id)
        return created

    def _convert_lead(self, lead_id):
        with patch("app.services.email_service.send_account_creation_email"):
            result = student_service.convert_lead_to_student_service(lead_id)
        if result.get("student") and result["student"].get("id"):
            self.cleanup_student_ids.append(result["student"]["id"])
        if result.get("user_id"):
            self.cleanup_user_ids.append(result["user_id"])
        return result

    def test_tc01_create_student_from_lead_sets_must_change_password_true(self):
        """TC-01: Tạo Student từ Lead -> account được tạo và must_change_password = True."""
        lead = self._create_won_lead()
        result = self._convert_lead(lead.id)

        self.assertTrue(result["account_created"])
        user_id = result["user_id"]
        self.assertIsNotNone(user_id)

        user = user_repository.get_user_by_id(user_id)
        self.assertIsNotNone(user)
        self.assertTrue(user.must_change_password)
        self.assertEqual(user.email, lead.email.lower())

    def test_tc02_check_database_password_hashed_not_plaintext(self):
        """TC-02: Kiểm tra database -> password được hash, không plaintext."""
        lead = self._create_won_lead()
        result = self._convert_lead(lead.id)

        user = user_repository.get_user_by_id(result["user_id"])
        self.assertIsNotNone(user)
        self.assertNotEqual(user.password_hash, self.test_initial_password)
        self.assertTrue(check_password_hash(user.password_hash, self.test_initial_password))
        self.assertFalse(self.test_initial_password in user.password_hash)

    def test_tc03_first_login_returns_must_change_password_true(self):
        """TC-03: Login lần đầu -> xác thực được nhưng response có must_change_password: true."""
        lead = self._create_won_lead()
        result = self._convert_lead(lead.id)

        login_resp = self.client.post(
            "/api/auth/login",
            json={"email": lead.email, "password": self.test_initial_password},
        )
        self.assertEqual(login_resp.status_code, 200)
        data = login_resp.get_json()
        self.assertTrue(data.get("must_change_password"))
        self.assertTrue(data.get("user", {}).get("must_change_password"))

    def test_tc04_protected_api_blocked_before_password_change(self):
        """TC-04: Thử truy cập API được bảo vệ (dashboard/leads/courses) trước khi đổi mật khẩu -> bị chặn 403."""
        lead = self._create_won_lead()
        result = self._convert_lead(lead.id)

        login_resp = self.client.post(
            "/api/auth/login",
            json={"email": lead.email, "password": self.test_initial_password},
        )
        token = login_resp.get_json()["access_token"]

        # Gọi một protected API yêu cầu permission (e.g. leads pipeline)
        api_resp = self.client.get(
            "/api/v1/leads/pipeline",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(api_resp.status_code, 403)
        data = api_resp.get_json()
        self.assertEqual(data.get("code"), "PASSWORD_CHANGE_REQUIRED")

        # Gọi endpoint đổi mật khẩu vẫn PHẢI cho phép
        check_change_resp = self.client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        # 400 Bad Request do thiếu password, chứng tỏ KHÔNG bị chặn 403 bởi decorator
        self.assertEqual(check_change_resp.status_code, 400)

    def test_tc05_change_password_clears_must_change_password_flag(self):
        """TC-05: Đổi mật khẩu thành công -> must_change_password = false."""
        lead = self._create_won_lead()
        result = self._convert_lead(lead.id)

        login_resp = self.client.post(
            "/api/auth/login",
            json={"email": lead.email, "password": self.test_initial_password},
        )
        token = login_resp.get_json()["access_token"]

        new_password = "NewStudent@2026StrongPass"
        change_resp = self.client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": self.test_initial_password,
                "new_password": new_password,
            },
        )
        self.assertEqual(change_resp.status_code, 200)

        user = user_repository.get_user_by_id(result["user_id"])
        self.assertFalse(user.must_change_password)

    def test_tc06_login_with_old_initial_password_fails_after_change(self):
        """TC-06: Login bằng mật khẩu ban đầu sau khi đổi -> không đăng nhập được (401)."""
        lead = self._create_won_lead()
        result = self._convert_lead(lead.id)

        login_resp = self.client.post(
            "/api/auth/login",
            json={"email": lead.email, "password": self.test_initial_password},
        )
        token = login_resp.get_json()["access_token"]

        new_password = "NewStudent@2026StrongPass"
        self.client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": self.test_initial_password,
                "new_password": new_password,
            },
        )

        old_login_resp = self.client.post(
            "/api/auth/login",
            json={"email": lead.email, "password": self.test_initial_password},
        )
        self.assertEqual(old_login_resp.status_code, 401)
        self.assertEqual(old_login_resp.get_json().get("code"), "INVALID_CREDENTIALS")

    def test_tc07_login_with_new_password_succeeds_normally(self):
        """TC-07: Login bằng mật khẩu mới -> đăng nhập bình thường, must_change_password = False."""
        lead = self._create_won_lead()
        result = self._convert_lead(lead.id)

        login_resp = self.client.post(
            "/api/auth/login",
            json={"email": lead.email, "password": self.test_initial_password},
        )
        token = login_resp.get_json()["access_token"]

        new_password = "NewStudent@2026StrongPass"
        self.client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": self.test_initial_password,
                "new_password": new_password,
            },
        )

        new_login_resp = self.client.post(
            "/api/auth/login",
            json={"email": lead.email, "password": new_password},
        )
        self.assertEqual(new_login_resp.status_code, 200)
        data = new_login_resp.get_json()
        self.assertFalse(data.get("must_change_password"))
        self.assertFalse(data.get("user", {}).get("must_change_password"))

    def test_tc08_existing_account_not_forced_to_change_password(self):
        """TC-08: Account cũ không thuộc flow này -> không tự nhiên bị bắt đổi mật khẩu."""
        admin_login = self.client.post(
            "/api/auth/login",
            json={"email": "admin.demo@daotao.edu.vn", "password": "Demo@123456"},
        )
        self.assertEqual(admin_login.status_code, 200)
        data = admin_login.get_json()
        self.assertFalse(data.get("must_change_password"))
        self.assertFalse(data.get("user", {}).get("must_change_password"))

    def test_tc09_missing_initial_password_env_raises_configuration_error(self):
        """TC-09: Khi không có STUDENT_INITIAL_PASSWORD -> báo CONFIGURATION_ERROR, không dùng mật khẩu yếu mặc định."""
        lead = self._create_won_lead()
        env_backup = os.environ.pop("STUDENT_INITIAL_PASSWORD", None)
        try:
            with self.assertRaises(StudentServiceError) as ctx:
                student_service.convert_lead_to_student_service(lead.id)

            self.assertEqual(ctx.exception.code, "CONFIGURATION_ERROR")
            self.assertEqual(ctx.exception.status_code, 500)
        finally:
            if env_backup is not None:
                os.environ["STUDENT_INITIAL_PASSWORD"] = env_backup

