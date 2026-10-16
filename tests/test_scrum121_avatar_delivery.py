"""
Bộ kiểm thử SCRUM-121 (Activity A4): Cung cấp ảnh đại diện an toàn cho giao diện (Secure Avatar Delivery).

Test Matrix:
1. GET JPEG avatar thành công
2. GET PNG avatar thành công
3. GET WEBP avatar thành công
4. Content-Type JPEG đúng (image/jpeg)
5. Content-Type PNG đúng (image/png)
6. Content-Type WEBP đúng (image/webp)
7. unauthenticated -> 401
8. avatar_path NULL -> 404 AVATAR_NOT_FOUND
9. file missing trên đĩa -> 404 AVATAR_NOT_FOUND
10. ../ path traversal trong DB không được serve -> 404 AVATAR_NOT_FOUND
11. absolute path ngoài storage trong DB không được serve -> 404 AVATAR_NOT_FOUND
12. symlink escape ngoài storage không được serve -> 404 AVATAR_NOT_FOUND
13. response không leak filesystem path
14. client user_id không override current user
15. client filename/path query parameters không có tác dụng
16. profile có avatar -> avatar_url đúng (/api/v1/users/profile/avatar)
17. profile không có avatar -> avatar_url = null
18. profile không leak avatar_path nội bộ
19. replace avatar xong GET trả ảnh mới
20. delete avatar xong GET trả về 404 AVATAR_NOT_FOUND
21. SCRUM-120 profile fields vẫn giữ nguyên đầy đủ
22. POST upload A2 vẫn PASS
23. DELETE avatar A3 vẫn PASS
24. Alias route GET /api/users/profile/avatar hoạt động đồng nhất
25. Cache-Control header no-cache hiện diện trong response
"""

import io
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from PIL import Image

from app.config.jwt_handlers import register_jwt_handlers
from app.config.avatar_config import configure_avatar
from app.database.connection import get_db_connection
from app.repositories import user_repository
from app.routes.user_routes import user_bp


def _create_image_buffer(format: str = "JPEG", size=(40, 40), color="blue") -> io.BytesIO:
    """Tạo buffer ảnh hợp lệ trong bộ nhớ bằng Pillow."""
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format=format)
    buf.seek(0)
    return buf


class Scrum121AvatarDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_parent_dir = tempfile.mkdtemp(prefix="test_avatar_delivery_parent_")
        cls.test_upload_dir = str(Path(cls.test_parent_dir) / "uploads" / "avatars")
        Path(cls.test_upload_dir).mkdir(parents=True, exist_ok=True)
        cls.outside_dir = str(Path(cls.test_parent_dir) / "outside")
        Path(cls.outside_dir).mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_parent_dir, ignore_errors=True)

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum121-delivery-at-least-32-bytes",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
            AVATAR_UPLOAD_FOLDER=self.test_upload_dir,
            AVATAR_MAX_FILE_SIZE=2 * 1024 * 1024,
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        configure_avatar(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()

        self.now = datetime.now(timezone.utc)
        self.user_a_id = f"test-usr-a-{int(datetime.now().timestamp() * 1000)}"
        self.user_b_id = f"test-usr-b-{int(datetime.now().timestamp() * 1000)}"
        self.session_a_id = f"sess-a-{self.user_a_id}"

        # Tạo user A và user B trong DB
        self.conn = get_db_connection()
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (id, email, password_hash, name, role, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (self.user_a_id, f"{self.user_a_id}@daotao.edu.vn", "hash_a", "Nguyễn Văn A", "trainee", "active"),
            )
            cur.execute(
                """
                INSERT INTO users (id, email, password_hash, name, role, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (self.user_b_id, f"{self.user_b_id}@daotao.edu.vn", "hash_b", "Trần Thị B", "trainer", "active"),
            )
            cur.execute(
                """
                INSERT INTO auth_sessions (
                    session_id, user_id, refresh_jti, created_at,
                    last_activity_at, idle_expires_at, absolute_expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self.session_a_id,
                    self.user_a_id,
                    "ref-jti-a",
                    self.now,
                    self.now,
                    self.now + timedelta(minutes=30),
                    self.now + timedelta(hours=8),
                ),
            )
        self.conn.commit()

    def tearDown(self):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM auth_sessions WHERE session_id = %s", (self.session_a_id,))
            cur.execute("DELETE FROM users WHERE id IN (%s, %s)", (self.user_a_id, self.user_b_id))
        self.conn.commit()
        self.conn.close()

    def _get_auth_headers(self, user_id=None, session_id=None):
        with self.app.app_context():
            token = create_access_token(
                identity=user_id or self.user_a_id,
                additional_claims={"sid": session_id or self.session_a_id},
            )
        return {"Authorization": f"Bearer {token}"}

    def _upload_avatar(self, user_id=None, session_id=None, format="JPEG", filename="avatar.jpg"):
        buf = _create_image_buffer(format=format)
        headers = self._get_auth_headers(user_id=user_id, session_id=session_id)
        mime = f"image/{format.lower()}" if format.lower() != "jpg" else "image/jpeg"
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data={"avatar": (buf, filename, mime)},
            headers=headers,
            content_type="multipart/form-data",
        )
        return res

    # =========================================================================
    # TESTS 1 - 6: DELIVER DIFFERENT FORMATS & CONTENT-TYPES
    # =========================================================================

    def test_01_get_jpeg_avatar_success(self):
        """1. GET JPEG avatar thành công -> HTTP 200, trả binary image."""
        self._upload_avatar(format="JPEG")
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertGreater(len(res.data), 0)

    def test_02_get_png_avatar_success(self):
        """2. GET PNG avatar thành công -> HTTP 200, trả binary image."""
        self._upload_avatar(format="PNG")
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertGreater(len(res.data), 0)

    def test_03_get_webp_avatar_success(self):
        """3. GET WEBP avatar thành công -> HTTP 200, trả binary image."""
        self._upload_avatar(format="WEBP")
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertGreater(len(res.data), 0)

    def test_04_content_type_jpeg_correct(self):
        """4. Content-Type khi trả JPEG avatar là image/jpeg."""
        self._upload_avatar(format="JPEG")
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.headers.get("Content-Type", "").startswith("image/jpeg"))

    def test_05_content_type_png_correct(self):
        """5. Content-Type khi trả PNG avatar là image/png."""
        self._upload_avatar(format="PNG")
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.headers.get("Content-Type", "").startswith("image/png"))

    def test_06_content_type_webp_correct(self):
        """6. Content-Type khi trả WEBP avatar là image/webp."""
        self._upload_avatar(format="WEBP")
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.headers.get("Content-Type", "").startswith("image/webp"))

    # =========================================================================
    # TESTS 7 - 13: SECURITY & ERROR HANDLING
    # =========================================================================

    def test_07_unauthenticated_get_returns_401(self):
        """7. Chưa đăng nhập (không có Bearer token) -> 401."""
        res = self.client.get("/api/v1/users/profile/avatar")
        self.assertEqual(res.status_code, 401)

    def test_08_avatar_path_null_returns_404_avatar_not_found(self):
        """8. Người dùng chưa có avatar (avatar_path = NULL) -> 404 AVATAR_NOT_FOUND."""
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 404)
        body = res.get_json()
        self.assertEqual(body.get("code"), "AVATAR_NOT_FOUND")

    def test_09_broken_avatar_file_missing_returns_404(self):
        """9. DB có avatar_path nhưng file trên đĩa bị mất -> 404 AVATAR_NOT_FOUND (không crash)."""
        user_repository.update_user_avatar(self.user_a_id, "avatars/broken_nonexistent.jpg")
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 404)
        body = res.get_json()
        self.assertEqual(body.get("code"), "AVATAR_NOT_FOUND")

    def test_10_path_traversal_dot_dot_rejected(self):
        """10. avatar_path chứa ../ không được serve -> 404 AVATAR_NOT_FOUND."""
        outside_file = Path(self.outside_dir) / "secret.txt"
        outside_file.write_text("classified data", encoding="utf-8")

        user_repository.update_user_avatar(self.user_a_id, "avatars/../../outside/secret.txt")
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 404)

    def test_11_absolute_path_outside_storage_rejected(self):
        """11. avatar_path là absolute path ngoài storage không được serve -> 404."""
        outside_file = Path(self.outside_dir) / "secret_abs.png"
        outside_file.write_bytes(b"\x89PNG\r\n\x1a\nfake")

        user_repository.update_user_avatar(self.user_a_id, str(outside_file.resolve()))
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 404)

    def test_12_symlink_escape_outside_storage_rejected(self):
        """12. Symlink bên trong upload dir trỏ ra ngoài storage không được serve -> 404."""
        outside_target = Path(self.outside_dir) / "outside_target.jpg"
        outside_target.write_bytes(b"\xff\xd8fake")

        symlink_path = Path(self.test_upload_dir) / "symlink_escape.jpg"
        user_repository.update_user_avatar(self.user_a_id, "avatars/symlink_escape.jpg")
        headers = self._get_auth_headers()

        try:
            os.symlink(str(outside_target.resolve()), str(symlink_path))
            res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
            self.assertEqual(res.status_code, 404)
        except (OSError, NotImplementedError):
            # Môi trường Windows không bật đặc quyền tạo symlink -> kiểm tra cơ chế phòng thủ ngoài storage
            fake_target = Path(self.test_upload_dir) / "symlink_escape.jpg"
            fake_target.write_bytes(b"\xff\xd8fake")
            with patch("pathlib.Path.is_relative_to", return_value=False):
                res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
                self.assertEqual(res.status_code, 404)


    def test_13_error_response_does_not_leak_filesystem_path(self):
        """13. Phản hồi lỗi không chứa đường dẫn tuyệt đối của máy chủ."""
        user_repository.update_user_avatar(self.user_a_id, "avatars/missing.jpg")
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        text = res.get_data(as_text=True)

        self.assertNotIn(str(self.test_upload_dir), text)
        self.assertNotIn("C:\\", text)
        self.assertNotIn("/tmp", text)

    def test_14_client_cannot_override_user_id(self):
        """14. Client gửi query param ?user_id=B không thể xem avatar của người khác thay vì của mình."""
        # User B có avatar
        self._upload_avatar(user_id=self.user_b_id, filename="user_b.jpg")
        # User A không có avatar
        headers_a = self._get_auth_headers(user_id=self.user_a_id)

        res = self.client.get(f"/api/v1/users/profile/avatar?user_id={self.user_b_id}", headers=headers_a)
        # User A không có avatar nên phải nhận 404, không được trả avatar của User B
        self.assertEqual(res.status_code, 404)

    def test_15_client_filename_or_path_ignored(self):
        """15. Client truyền ?filename=other.jpg&path=/etc/passwd bị bỏ qua hoàn toàn."""
        self._upload_avatar(format="JPEG")
        headers = self._get_auth_headers()
        res = self.client.get(
            "/api/v1/users/profile/avatar?filename=other.jpg&path=../../etc/passwd",
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)

    # =========================================================================
    # TESTS 16 - 21: PROFILE CONTRACT & LIFECYCLE
    # =========================================================================

    def test_16_profile_has_avatar_returns_avatar_url(self):
        """16. GET profile của user có avatar trả avatar_url = '/api/v1/users/profile/avatar'."""
        self._upload_avatar(format="JPEG")
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data.get("avatar_url"), "/api/v1/users/profile/avatar")

    def test_17_profile_no_avatar_returns_avatar_url_null(self):
        """17. GET profile của user chưa có avatar trả avatar_url = null."""
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertIsNone(data.get("avatar_url"))

    def test_18_profile_does_not_leak_avatar_path(self):
        """18. GET profile không trả avatar_path (không làm lộ cấu trúc lưu trữ nội bộ)."""
        self._upload_avatar(format="JPEG")
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertNotIn("avatar_path", data)

    def test_19_replace_avatar_reflects_in_subsequent_get(self):
        """19. Sau khi replace avatar -> GET /profile/avatar trả ngay dữ liệu của ảnh mới."""
        # Upload ảnh 1 (JPEG)
        self._upload_avatar(format="JPEG")
        headers = self._get_auth_headers()
        res_1 = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res_1.status_code, 200)
        self.assertTrue(res_1.headers["Content-Type"].startswith("image/jpeg"))

        # Upload ảnh 2 (PNG) thay thế
        self._upload_avatar(format="PNG")
        res_2 = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res_2.status_code, 200)
        self.assertTrue(res_2.headers["Content-Type"].startswith("image/png"))

    def test_20_delete_avatar_causes_subsequent_get_to_return_404(self):
        """20. Sau khi DELETE avatar -> GET /profile/avatar trả về 404 AVATAR_NOT_FOUND."""
        self._upload_avatar(format="JPEG")
        headers = self._get_auth_headers()
        # Xác nhận có avatar
        res_before = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res_before.status_code, 200)

        # Xóa avatar
        del_res = self.client.delete("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(del_res.status_code, 200)

        # GET lại -> 404
        res_after = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res_after.status_code, 404)
        self.assertEqual(res_after.get_json()["code"], "AVATAR_NOT_FOUND")

    def test_21_scrum120_profile_fields_intact(self):
        """21. Tất cả các trường hồ sơ cá nhân SCRUM-120 vẫn giữ nguyên đầy đủ."""
        self._upload_avatar(format="JPEG")
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        expected_fields = {"id", "name", "email", "phone", "date_of_birth", "address", "role", "avatar_url"}
        for f in expected_fields:
            self.assertIn(f, data)
        self.assertEqual(data["name"], "Nguyễn Văn A")
        self.assertEqual(data["role"], "trainee")

    # =========================================================================
    # TESTS 22 - 25: REGRESSION & ALIAS & CACHE
    # =========================================================================

    def test_22_post_upload_a2_still_passes(self):
        """22. POST upload A2 vẫn hoạt động bình thường."""
        res = self._upload_avatar(format="PNG")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

    def test_23_delete_avatar_a3_still_passes(self):
        """23. DELETE avatar A3 vẫn hoạt động bình thường."""
        self._upload_avatar(format="WEBP")
        headers = self._get_auth_headers()
        res = self.client.delete("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["message"], "Đã xóa ảnh đại diện.")

    def test_24_alias_route_get_avatar_works(self):
        """24. Alias route GET /api/users/profile/avatar hoạt động chính xác tương tự /api/v1/..."""
        self._upload_avatar(format="WEBP")
        headers = self._get_auth_headers()
        res = self.client.get("/api/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.headers["Content-Type"].startswith("image/webp"))

    def test_25_cache_control_headers_present(self):
        """25. Response GET avatar chứa header Cache-Control no-cache."""
        self._upload_avatar(format="JPEG")
        headers = self._get_auth_headers()
        res = self.client.get("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)
        cache_control = res.headers.get("Cache-Control", "")
        self.assertIn("no-cache", cache_control)


if __name__ == "__main__":
    unittest.main()
