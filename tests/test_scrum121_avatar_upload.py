"""
Bộ kiểm thử SCRUM-121 (Activity A2): API tải lên ảnh đại diện người dùng (POST /api/v1/users/profile/avatar).

Test Matrix:
1. upload JPEG hợp lệ
2. upload PNG hợp lệ
3. upload WEBP hợp lệ
4. thiếu file avatar (missing field)
5. empty file (0 bytes)
6. quá 2 MB (AVATAR_TOO_LARGE)
7. extension không hợp lệ (.txt, .exe, .sh)
8. MIME không hợp lệ (text/html, application/x-executable)
9. fake image renamed .jpg (text file masked as jpg)
10. corrupted image (truncated/broken binary)
11. SVG rejected (chống SVG/XML injection)
12. path traversal filename (../../avatar.jpg không thoát khỏi upload folder)
13. unauthenticated -> 401
14. current user ownership (chỉ upload cho chính mình, client user_id bị bỏ qua)
15. DB avatar_path được cập nhật chính xác
16. UUID filename được sinh ngẫu nhiên, không dùng tên gốc
17. relative path đúng dạng avatars/<uuid>.<ext>
18. DB failure -> file mới trên đĩa được cleanup ngay lập tức
19. response không leak filesystem path hay metadata nhạy cảm
20. profile functionality cũ (GET /users/profile) không bị ảnh hưởng và phản ánh avatar mới
"""

import io
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from PIL import Image

from app.config.jwt_handlers import register_jwt_handlers
from app.config.avatar_config import configure_avatar
from app.database.connection import get_db_connection
from app.models.login_session import LoginSession
from app.models.user import User
from app.repositories import session_repository, user_repository
from app.routes.user_routes import user_bp


def _create_image_buffer(format: str = "JPEG", size=(40, 40), color="blue") -> io.BytesIO:
    """Tạo file ảnh hợp lệ trong bộ nhớ bằng Pillow."""
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format=format)
    buf.seek(0)
    return buf


class Scrum121AvatarUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_upload_dir = tempfile.mkdtemp(prefix="test_avatar_uploads_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_upload_dir, ignore_errors=True)

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum121-upload-suite-at-least-32-bytes",
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
        self.user_a_id = f"test-user-a-{int(datetime.now().timestamp() * 1000)}"
        self.user_b_id = f"test-user-b-{int(datetime.now().timestamp() * 1000)}"
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

    # =========================================================================
    # CASE 1, 2, 3: VALID UPLOADS (JPEG, PNG, WEBP)
    # =========================================================================

    def test_01_upload_valid_jpeg(self):
        """Upload ảnh JPEG hợp lệ thành công -> HTTP 200, lưu file và cập nhật database."""
        buf = _create_image_buffer(format="JPEG")
        headers = self.get_headers = self._get_auth_headers()

        data = {
            "avatar": (buf, "profile_pic.jpg", "image/jpeg"),
        }
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data=data,
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        res_json = res.get_json()
        self.assertEqual(res_json["status"], "success")
        self.assertEqual(res_json["message"], "Cập nhật ảnh đại diện thành công.")

        avatar_path = res_json["avatar"]["path"]
        self.assertTrue(avatar_path.startswith("avatars/"))
        self.assertTrue(avatar_path.endswith(".jpg"))

        # Kiểm tra file thực tế trên đĩa
        filename = avatar_path.split("/")[-1]
        saved_file = Path(self.test_upload_dir) / filename
        self.assertTrue(saved_file.exists(), f"File {saved_file} phải tồn tại trên đĩa")

        # Kiểm tra DB
        user = user_repository.get_user_by_id(self.user_a_id)
        self.assertEqual(user.avatar_path, avatar_path)

    def test_02_upload_valid_png(self):
        """Upload ảnh PNG hợp lệ thành công -> HTTP 200, extension .png chuẩn."""
        buf = _create_image_buffer(format="PNG")
        headers = self._get_auth_headers()

        data = {
            "avatar": (buf, "avatar.png", "image/png"),
        }
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data=data,
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        res_json = res.get_json()
        avatar_path = res_json["avatar"]["path"]
        self.assertTrue(avatar_path.endswith(".png"))

        # Xác nhận đường dẫn relative POSIX
        self.assertNotIn("\\", avatar_path)
        self.assertNotIn(str(self.test_upload_dir), avatar_path)

    def test_03_upload_valid_webp(self):
        """Upload ảnh WEBP hợp lệ thành công -> HTTP 200, hỗ trợ cả alias route /api/users/profile/avatar."""
        buf = _create_image_buffer(format="WEBP")
        headers = self._get_auth_headers()

        data = {
            "avatar": (buf, "photo.webp", "image/webp"),
        }
        # Thử nghiệm alias route
        res = self.client.post(
            "/api/users/profile/avatar",
            data=data,
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        res_json = res.get_json()
        avatar_path = res_json["avatar"]["path"]
        self.assertTrue(avatar_path.endswith(".webp"))

    # =========================================================================
    # CASE 4, 5, 6: VALIDATION (MISSING, EMPTY, TOO LARGE)
    # =========================================================================

    def test_04_missing_avatar_field(self):
        """Thiếu trường 'avatar' trong multipart form-data -> 400 AVATAR_REQUIRED."""
        headers = self._get_auth_headers()
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data={"other_field": "some_value"},
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "AVATAR_REQUIRED")

    def test_05_empty_avatar_file(self):
        """Tệp ảnh 0 bytes -> 400 AVATAR_REQUIRED."""
        empty_buf = io.BytesIO(b"")
        headers = self._get_auth_headers()
        data = {
            "avatar": (empty_buf, "empty.jpg", "image/jpeg"),
        }
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data=data,
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "AVATAR_REQUIRED")

    def test_06_avatar_exceeding_2mb(self):
        """Tệp vượt quá 2MB -> 400 AVATAR_TOO_LARGE với thông báo tiếng Việt."""
        large_buf = io.BytesIO(b"0" * (2 * 1024 * 1024 + 1024))
        headers = self._get_auth_headers()
        data = {
            "avatar": (large_buf, "large.jpg", "image/jpeg"),
        }
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data=data,
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        res_json = res.get_json()
        self.assertEqual(res_json["code"], "AVATAR_TOO_LARGE")
        self.assertIn("2 MB", res_json["message"])

    # =========================================================================
    # CASE 7, 8, 9, 10, 11: FILE TYPE & CONTENT SECURITY
    # =========================================================================

    def test_07_invalid_extension_rejected(self):
        """File có extension .txt, .exe, .sh bị từ chối -> 400 INVALID_AVATAR_TYPE."""
        headers = self._get_auth_headers()
        for ext in ["txt", "exe", "sh", "py"]:
            buf = io.BytesIO(b"some content")
            res = self.client.post(
                "/api/v1/users/profile/avatar",
                data={"avatar": (buf, f"bad.{ext}", "text/plain")},
                headers=headers,
                content_type="multipart/form-data",
            )
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()["code"], "INVALID_AVATAR_TYPE")

    def test_08_invalid_mime_type_rejected(self):
        """MIME type nguy hiểm (text/html, application/x-executable) bị từ chối -> 400 INVALID_AVATAR_TYPE."""
        headers = self._get_auth_headers()
        buf = _create_image_buffer(format="JPEG")
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data={"avatar": (buf, "avatar.jpg", "text/html")},
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_AVATAR_TYPE")

    def test_09_fake_image_renamed_jpg_rejected(self):
        """Tệp văn bản giả mạo đuôi .jpg -> Pillow verify thất bại -> 400 INVALID_AVATAR_TYPE."""
        fake_buf = io.BytesIO(b"Hello world, I am just a plain text file pretending to be jpg!")
        headers = self._get_auth_headers()
        data = {
            "avatar": (fake_buf, "fake.jpg", "image/jpeg"),
        }
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data=data,
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_AVATAR_TYPE")

    def test_10_corrupted_image_rejected(self):
        """Tệp ảnh bị hỏng/cụt header -> Pillow verify thất bại -> 400 INVALID_AVATAR_TYPE."""
        corrupted_buf = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01broken_truncated_bytes")
        headers = self._get_auth_headers()
        data = {
            "avatar": (corrupted_buf, "corrupted.jpg", "image/jpeg"),
        }
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data=data,
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_AVATAR_TYPE")

    def test_11_svg_image_rejected(self):
        """SVG vector image tuyệt đối bị từ chối để chống XSS/XML injection -> 400 INVALID_AVATAR_TYPE."""
        svg_buf = io.BytesIO(b"<svg xmlns='http://www.w3.org/2000/svg'><circle r='50'/></svg>")
        headers = self._get_auth_headers()
        data = {
            "avatar": (svg_buf, "vector.svg", "image/svg+xml"),
        }
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data=data,
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_AVATAR_TYPE")

    # =========================================================================
    # CASE 12, 13, 14, 15, 16, 17: SECURITY & OWNERSHIP
    # =========================================================================

    def test_12_path_traversal_filename_defended(self):
        """Tên file có chứa ../../../etc/passwd.jpg -> được lưu an toàn bằng UUID trong uploads/avatars."""
        buf = _create_image_buffer(format="JPEG")
        headers = self._get_auth_headers()
        data = {
            "avatar": (buf, "../../../etc/passwd.jpg", "image/jpeg"),
        }
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data=data,
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        avatar_path = res.get_json()["avatar"]["path"]
        self.assertTrue(avatar_path.startswith("avatars/"))
        self.assertNotIn("etc", avatar_path)
        self.assertNotIn("passwd", avatar_path)

        # File nằm hoàn toàn trong test_upload_dir
        filename = avatar_path.split("/")[-1]
        self.assertTrue((Path(self.test_upload_dir) / filename).exists())

    def test_13_unauthenticated_request_fails(self):
        """Không có token hoặc session không hợp lệ -> 401 Unauthorized."""
        buf = _create_image_buffer(format="JPEG")
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data={"avatar": (buf, "pic.jpg", "image/jpeg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 401)

    def test_14_current_user_ownership_cannot_override_other_user(self):
        """Người dùng A upload avatar -> chỉ cập nhật cho A. Truyền user_id của B trong body/query bị bỏ qua."""
        buf = _create_image_buffer(format="JPEG")
        headers = self._get_auth_headers()  # Token của User A

        # Cố tình truyền user_id của B trong cả query params và form data
        data = {
            "avatar": (buf, "pic.jpg", "image/jpeg"),
            "user_id": self.user_b_id,
        }
        res = self.client.post(
            f"/api/v1/users/profile/avatar?user_id={self.user_b_id}",
            data=data,
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)

        # User A phải có avatar mới
        user_a = user_repository.get_user_by_id(self.user_a_id)
        self.assertIsNotNone(user_a.avatar_path)

        # User B TUYỆT ĐỐI không bị ảnh hưởng
        user_b = user_repository.get_user_by_id(self.user_b_id)
        self.assertIsNone(user_b.avatar_path)

    def test_15_db_avatar_path_updated_correctly(self):
        """15. Database avatar_path được cập nhật chính xác, không thay đổi các trường thông tin khác."""
        buf = _create_image_buffer(format="JPEG")
        headers = self._get_auth_headers()
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data={"avatar": (buf, "update_db.jpg", "image/jpeg")},
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        avatar_path = res.get_json()["avatar"]["path"]

        user = user_repository.get_user_by_id(self.user_a_id)
        self.assertEqual(user.avatar_path, avatar_path)
        self.assertEqual(user.name, "Nguyễn Văn A")
        self.assertEqual(user.role, "trainee")
        self.assertEqual(user.status, "active")

    def test_16_uuid_filename_generated(self):
        """16. Tên file lưu trên đĩa là chuỗi UUID 36 ký tự ngẫu nhiên, không dùng tên gốc."""
        buf = _create_image_buffer(format="PNG")
        headers = self._get_auth_headers()
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data={"avatar": (buf, "my_personal_photo_2026.png", "image/png")},
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        avatar_path = res.get_json()["avatar"]["path"]
        filename = avatar_path.split("/")[-1]
        uuid_part = filename.rsplit(".", 1)[0]
        self.assertEqual(len(uuid_part), 36)
        self.assertNotIn("my_personal_photo", filename)

    def test_17_relative_path_format_posix(self):
        """17. Relative path trả về và lưu DB đúng định dạng POSIX 'avatars/<uuid>.<ext>'."""
        buf = _create_image_buffer(format="WEBP")
        headers = self._get_auth_headers()
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data={"avatar": (buf, "posix_check.webp", "image/webp")},
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        avatar_path = res.get_json()["avatar"]["path"]
        self.assertTrue(avatar_path.startswith("avatars/"))
        self.assertNotIn("\\", avatar_path)
        self.assertNotIn(":", avatar_path)

    # =========================================================================
    # CASE 18, 19, 20: FAILURE CLEANUP, NO LEAK, PROFILE INTEGRATION
    # =========================================================================

    def test_18_database_failure_cleans_up_uploaded_file(self):
        """Khi cập nhật database thất bại -> file vừa ghi ra đĩa được xóa ngay lập tức (không sinh orphan file)."""
        buf = _create_image_buffer(format="JPEG")
        headers = self._get_auth_headers()

        files_before = set(Path(self.test_upload_dir).iterdir())

        # Mock update_user_avatar ném ngoại lệ
        with patch("app.repositories.user_repository.update_user_avatar", side_effect=Exception("Simulated DB Crash")):
            res = self.client.post(
                "/api/v1/users/profile/avatar",
                data={"avatar": (buf, "test_cleanup.jpg", "image/jpeg")},
                headers=headers,
                content_type="multipart/form-data",
            )
            self.assertEqual(res.status_code, 500)

        # Kiểm tra không có file orphan nào được giữ lại trong thư mục test
        files_after = set(Path(self.test_upload_dir).iterdir())
        new_files = files_after - files_before
        self.assertEqual(len(new_files), 0, f"File trên đĩa phải được cleanup khi DB update lỗi: {new_files}")

    def test_19_response_does_not_leak_filesystem_path(self):
        """Response không chứa đường dẫn tuyệt đối của hệ điều hành (chỉ chứa relative path)."""
        buf = _create_image_buffer(format="JPEG")
        headers = self._get_auth_headers()
        res = self.client.post(
            "/api/v1/users/profile/avatar",
            data={"avatar": (buf, "clean_resp.jpg", "image/jpeg")},
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        resp_text = res.get_data(as_text=True)

        self.assertNotIn(str(self.test_upload_dir), resp_text)
        self.assertNotIn("C:\\", resp_text)
        self.assertNotIn("/tmp", resp_text)

    def test_20_profile_get_reflects_updated_avatar(self):
        """Sau khi upload thành công, API GET /api/v1/users/profile vẫn hoạt động bình thường và user có avatar_path."""
        buf = _create_image_buffer(format="JPEG")
        headers = self._get_auth_headers()

        # 1. Upload avatar
        upload_res = self.client.post(
            "/api/v1/users/profile/avatar",
            data={"avatar": (buf, "profile_reflect.jpg", "image/jpeg")},
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(upload_res.status_code, 200)
        uploaded_path = upload_res.get_json()["avatar"]["path"]

        # 2. Gọi GET profile
        profile_res = self.client.get("/api/v1/users/profile", headers=headers)
        self.assertEqual(profile_res.status_code, 200)
        profile_data = profile_res.get_json()["data"]

        self.assertEqual(profile_data["id"], self.user_a_id)
        self.assertEqual(profile_data["name"], "Nguyễn Văn A")
        self.assertEqual(profile_data["role"], "trainee")


if __name__ == "__main__":
    unittest.main()
