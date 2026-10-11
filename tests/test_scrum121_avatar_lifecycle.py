"""
Bộ kiểm thử SCRUM-121 (Activity A3): Hoàn thiện vòng đời avatar (Thay thế và Xóa ảnh đại diện).

Test Matrix:
REPLACE:
1. user chưa có avatar → upload thành công
2. user có avatar → upload mới thành công
3. DB trỏ avatar mới
4. avatar cũ bị xóa sau DB success
5. avatar mới tồn tại trên đĩa
6. DB update fail → avatar mới bị cleanup
7. DB update fail → avatar cũ vẫn tồn tại trên đĩa
8. DB update fail → DB vẫn giữ avatar cũ
9. avatar cũ bị missing trên disk → replace vẫn thành công
10. avatar_path cũ chứa ../ → không xóa file ngoài storage
11. avatar_path cũ absolute ngoài storage → không xóa file đó

DELETE:
12. delete avatar thành công
13. DB avatar_path trở về NULL
14. file avatar cũ trên đĩa bị xóa
15. unauthenticated → 401
16. không nhận client user_id override
17. user không có avatar → DELETE vẫn idempotent thành công (HTTP 200)
18. file avatar cũ đã mất trên đĩa → DELETE vẫn thành công
19. malicious avatar_path trong DB → không xóa file ngoài storage
20. filesystem delete fail → DB vẫn giữ NULL (không rollback)
21. response không leak internal filesystem path

REGRESSION:
22. POST upload A2 vẫn hoạt động với cả alias route
23. GET profile phản ánh đúng trạng thái sau replace và sau delete
24. PUT profile update (SCRUM-120) không bị ảnh hưởng và giữ nguyên avatar
25. DELETE alias route (/api/users/profile/avatar) hoạt động nhất quán
"""

import io
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


class Scrum121AvatarLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Tạo thư mục cha chứa upload folder và canary outside folder
        cls.test_parent_dir = tempfile.mkdtemp(prefix="test_avatar_lifecycle_parent_")
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
            JWT_SECRET_KEY="test-secret-key-scrum121-lifecycle-at-least-32-bytes",
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
    # REPLACE MATRIX: 1 -> 11
    # =========================================================================

    def test_01_user_without_avatar_upload_success(self):
        """1. User chưa có avatar -> upload thành công, lưu file và cập nhật DB."""
        user = user_repository.get_user_by_id(self.user_a_id)
        self.assertIsNone(user.avatar_path)

        res = self._upload_avatar(format="JPEG")
        self.assertEqual(res.status_code, 200)
        res_json = res.get_json()
        self.assertEqual(res_json["status"], "success")

        avatar_path = res_json["avatar"]["path"]
        self.assertTrue(avatar_path.startswith("avatars/"))

        # Kiểm tra file trên đĩa
        filename = avatar_path.split("/")[-1]
        self.assertTrue((Path(self.test_upload_dir) / filename).exists())

        # Kiểm tra DB
        user_after = user_repository.get_user_by_id(self.user_a_id)
        self.assertEqual(user_after.avatar_path, avatar_path)

    def test_02_user_with_avatar_upload_new_success(self):
        """2. User có avatar -> upload mới thành công (HTTP 200)."""
        res_old = self._upload_avatar(format="JPEG", filename="old_pic.jpg")
        self.assertEqual(res_old.status_code, 200)

        res_new = self._upload_avatar(format="PNG", filename="new_pic.png")
        self.assertEqual(res_new.status_code, 200)
        self.assertEqual(res_new.get_json()["status"], "success")

    def test_03_db_points_to_new_avatar(self):
        """3. Sau khi upload thay thế -> DB trỏ đúng relative path của avatar mới."""
        res_old = self._upload_avatar(format="JPEG", filename="old_pic.jpg")
        old_avatar = res_old.get_json()["avatar"]["path"]

        res_new = self._upload_avatar(format="PNG", filename="new_pic.png")
        new_avatar = res_new.get_json()["avatar"]["path"]

        user = user_repository.get_user_by_id(self.user_a_id)
        self.assertEqual(user.avatar_path, new_avatar)
        self.assertNotEqual(user.avatar_path, old_avatar)

    def test_04_old_avatar_deleted_after_db_success(self):
        """4. Avatar cũ bị xóa an toàn khỏi đĩa sau khi DB update thành công."""
        res_old = self._upload_avatar(format="JPEG", filename="old_pic.jpg")
        old_file = Path(self.test_upload_dir) / res_old.get_json()["avatar"]["path"].split("/")[-1]
        self.assertTrue(old_file.exists())

        self._upload_avatar(format="PNG", filename="new_pic.png")
        self.assertFalse(old_file.exists(), f"File cũ {old_file} phải bị xóa khỏi đĩa sau khi replace")

    def test_05_new_avatar_exists_on_disk(self):
        """5. Avatar mới tồn tại thực tế trên đĩa sau khi replace thành công."""
        self._upload_avatar(format="JPEG", filename="old_pic.jpg")
        res_new = self._upload_avatar(format="WEBP", filename="new_pic.webp")
        new_file = Path(self.test_upload_dir) / res_new.get_json()["avatar"]["path"].split("/")[-1]
        self.assertTrue(new_file.exists(), f"File mới {new_file} phải tồn tại trên đĩa")

    def test_06_db_update_fail_during_replace_cleans_up_new_avatar(self):
        """6. DB update fail -> avatar mới bị cleanup ngay lập tức (không để lại orphan file)."""
        res_old = self._upload_avatar(format="JPEG", filename="initial.jpg")
        self.assertEqual(res_old.status_code, 200)

        files_before = set(Path(self.test_upload_dir).iterdir())

        buf = _create_image_buffer(format="PNG")
        headers = self._get_auth_headers()
        with patch("app.repositories.user_repository.update_user_avatar", side_effect=Exception("DB Crash")):
            res_fail = self.client.post(
                "/api/v1/users/profile/avatar",
                data={"avatar": (buf, "failed_new.png", "image/png")},
                headers=headers,
                content_type="multipart/form-data",
            )
            self.assertEqual(res_fail.status_code, 500)

        files_after = set(Path(self.test_upload_dir).iterdir())
        self.assertEqual(len(files_after - files_before), 0, "Avatar mới phải được cleanup khi DB fail")

    def test_07_db_update_fail_during_replace_keeps_old_avatar_on_disk(self):
        """7. DB update fail -> avatar cũ vẫn tồn tại trên đĩa."""
        res_old = self._upload_avatar(format="JPEG", filename="initial.jpg")
        old_file = Path(self.test_upload_dir) / res_old.get_json()["avatar"]["path"].split("/")[-1]
        self.assertTrue(old_file.exists())

        buf = _create_image_buffer(format="PNG")
        headers = self._get_auth_headers()
        with patch("app.repositories.user_repository.update_user_avatar", side_effect=Exception("DB Crash")):
            self.client.post(
                "/api/v1/users/profile/avatar",
                data={"avatar": (buf, "failed_new.png", "image/png")},
                headers=headers,
                content_type="multipart/form-data",
            )

        self.assertTrue(old_file.exists(), "Avatar cũ phải tiếp tục tồn tại trên đĩa khi DB update fail")

    def test_08_db_update_fail_during_replace_keeps_old_avatar_in_db(self):
        """8. DB update fail -> DB vẫn trỏ vào avatar cũ."""
        res_old = self._upload_avatar(format="JPEG", filename="initial.jpg")
        old_path = res_old.get_json()["avatar"]["path"]

        buf = _create_image_buffer(format="PNG")
        headers = self._get_auth_headers()
        with patch("app.repositories.user_repository.update_user_avatar", side_effect=Exception("DB Crash")):
            self.client.post(
                "/api/v1/users/profile/avatar",
                data={"avatar": (buf, "failed_new.png", "image/png")},
                headers=headers,
                content_type="multipart/form-data",
            )

        user = user_repository.get_user_by_id(self.user_a_id)
        self.assertEqual(user.avatar_path, old_path, "DB vẫn phải lưu đường dẫn avatar cũ")

    def test_09_old_avatar_missing_on_disk_replace_succeeds(self):
        """9. avatar cũ bị missing trên disk -> replace vẫn thành công, không crash."""
        # Gán trực tiếp avatar_path không có file thật trên đĩa vào DB
        user_repository.update_user_avatar(self.user_a_id, "avatars/already-missing-file.jpg")

        res = self._upload_avatar(format="WEBP", filename="replacement.webp")
        self.assertEqual(res.status_code, 200)

        user = user_repository.get_user_by_id(self.user_a_id)
        self.assertTrue(user.avatar_path.endswith(".webp"))
        new_file = Path(self.test_upload_dir) / user.avatar_path.split("/")[-1]
        self.assertTrue(new_file.exists())

    def test_10_malformed_old_avatar_path_traversal_does_not_delete_outside(self):
        """10. avatar_path cũ chứa ../ -> replace không xóa file ngoài storage."""
        # Tạo canary file bên ngoài upload folder
        canary_file = Path(self.outside_dir) / "canary_10.txt"
        canary_file.write_text("critical secret data 10", encoding="utf-8")
        self.assertTrue(canary_file.exists())

        # Gán avatar_path bất thường chứa traversal
        user_repository.update_user_avatar(self.user_a_id, "avatars/../../outside/canary_10.txt")

        # Upload avatar mới
        res = self._upload_avatar(format="JPEG")
        self.assertEqual(res.status_code, 200)

        # Canary file ngoài storage tuyệt đối KHÔNG bị xóa
        self.assertTrue(canary_file.exists(), "Canary file ngoài storage không được phép bị xóa!")

    def test_11_malformed_old_avatar_absolute_path_does_not_delete_outside(self):
        """11. avatar_path cũ là absolute path ngoài storage -> replace không xóa file đó."""
        canary_file = Path(self.outside_dir) / "canary_11.txt"
        canary_file.write_text("critical secret data 11", encoding="utf-8")
        self.assertTrue(canary_file.exists())

        # Gán avatar_path absolute vào DB
        user_repository.update_user_avatar(self.user_a_id, str(canary_file.resolve()))

        # Upload avatar mới
        res = self._upload_avatar(format="PNG")
        self.assertEqual(res.status_code, 200)

        # Canary file không bị xóa
        self.assertTrue(canary_file.exists(), "File ngoài storage có absolute path không được phép bị xóa!")

    # =========================================================================
    # DELETE MATRIX: 12 -> 21
    # =========================================================================

    def test_12_delete_avatar_success_returns_200(self):
        """12. delete avatar thành công trả về HTTP 200, status success, avatar: null."""
        self._upload_avatar(format="JPEG")
        headers = self._get_auth_headers()
        res_del = self.client.delete("/api/v1/users/profile/avatar", headers=headers)

        self.assertEqual(res_del.status_code, 200)
        del_json = res_del.get_json()
        self.assertEqual(del_json["status"], "success")
        self.assertEqual(del_json["message"], "Đã xóa ảnh đại diện.")
        self.assertIsNone(del_json["avatar"])
        self.assertIsNone(del_json["data"]["avatar_path"])

    def test_13_delete_avatar_clears_db_avatar_path_to_null(self):
        """13. delete avatar thành công -> DB avatar_path trở về NULL."""
        self._upload_avatar(format="JPEG")
        headers = self._get_auth_headers()
        self.client.delete("/api/v1/users/profile/avatar", headers=headers)

        user = user_repository.get_user_by_id(self.user_a_id)
        self.assertIsNone(user.avatar_path)

    def test_14_delete_avatar_removes_file_from_disk(self):
        """14. delete avatar thành công -> file avatar trên đĩa bị xóa sạch."""
        res_upload = self._upload_avatar(format="JPEG")
        avatar_path = res_upload.get_json()["avatar"]["path"]
        avatar_file = Path(self.test_upload_dir) / avatar_path.split("/")[-1]
        self.assertTrue(avatar_file.exists())

        headers = self._get_auth_headers()
        self.client.delete("/api/v1/users/profile/avatar", headers=headers)

        self.assertFalse(avatar_file.exists(), f"File avatar {avatar_file} phải bị xóa khỏi đĩa")

    def test_15_unauthenticated_delete_returns_401(self):
        """15. unauthenticated -> 401 Unauthorized khi gọi DELETE."""
        res = self.client.delete("/api/v1/users/profile/avatar")
        self.assertEqual(res.status_code, 401)

    def test_16_client_cannot_override_user_id_on_delete(self):
        """16. không nhận client user_id override: User A delete không thể xóa avatar của User B."""
        # Gán avatar cho user B
        user_repository.update_user_avatar(self.user_b_id, "avatars/user_b_avatar.jpg")

        # User A gọi DELETE kèm query param và body user_id của B
        headers = self._get_auth_headers()  # Token của A
        res = self.client.delete(
            f"/api/v1/users/profile/avatar?user_id={self.user_b_id}",
            json={"user_id": self.user_b_id},
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)

        # User B không bị ảnh hưởng
        user_b = user_repository.get_user_by_id(self.user_b_id)
        self.assertEqual(user_b.avatar_path, "avatars/user_b_avatar.jpg")

    def test_17_delete_when_no_avatar_is_idempotent_success(self):
        """17. user không có avatar -> DELETE vẫn idempotent thành công (HTTP 200, avatar: null)."""
        user = user_repository.get_user_by_id(self.user_a_id)
        self.assertIsNone(user.avatar_path)

        headers = self._get_auth_headers()
        res = self.client.delete("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)
        res_json = res.get_json()
        self.assertEqual(res_json["status"], "success")
        self.assertIsNone(res_json["avatar"])

    def test_18_delete_when_file_already_missing_on_disk_succeeds(self):
        """18. file đã mất trên đĩa -> DELETE vẫn thành công, DB chuyển về NULL."""
        user_repository.update_user_avatar(self.user_a_id, "avatars/lost_file.jpg")

        headers = self._get_auth_headers()
        res = self.client.delete("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)

        user = user_repository.get_user_by_id(self.user_a_id)
        self.assertIsNone(user.avatar_path)

    def test_19_malicious_avatar_path_on_delete_does_not_delete_outside(self):
        """19. malicious avatar_path -> không xóa ngoài storage."""
        canary = Path(self.outside_dir) / "canary_19.txt"
        canary.write_text("critical secret data 19", encoding="utf-8")
        self.assertTrue(canary.exists())

        user_repository.update_user_avatar(self.user_a_id, "../../outside/canary_19.txt")

        headers = self._get_auth_headers()
        res = self.client.delete("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)

        # Canary file ngoài storage không bị xóa
        self.assertTrue(canary.exists())
        # DB vẫn được dọn sạch về NULL
        user = user_repository.get_user_by_id(self.user_a_id)
        self.assertIsNone(user.avatar_path)

    def test_20_filesystem_delete_fail_leaves_db_as_null(self):
        """20. filesystem delete fail -> DB vẫn NULL (không rollback, không để DB trỏ vào resource hỏng)."""
        res_upload = self._upload_avatar(format="JPEG")
        self.assertEqual(res_upload.status_code, 200)
        avatar_path = res_upload.get_json()["avatar"]["path"]

        headers = self._get_auth_headers()
        # Mock delete_avatar_file trả về False (giả lập lỗi filesystem quyền hạn)
        with patch("app.services.avatar_service.delete_avatar_file", return_value=False):
            res = self.client.delete("/api/v1/users/profile/avatar", headers=headers)
            self.assertEqual(res.status_code, 200)

        # DB vẫn là NULL, không rollback
        user = user_repository.get_user_by_id(self.user_a_id)
        self.assertIsNone(user.avatar_path)

    def test_21_response_does_not_leak_internal_filesystem_path(self):
        """21. Response khi DELETE không leak internal filesystem path hay metadata nhạy cảm."""
        self._upload_avatar(format="JPEG")
        headers = self._get_auth_headers()
        res = self.client.delete("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)
        text = res.get_data(as_text=True)

        self.assertNotIn(str(self.test_upload_dir), text)
        self.assertNotIn("C:\\", text)
        self.assertNotIn("/tmp", text)

    # =========================================================================
    # REGRESSION MATRIX: 22 -> 25
    # =========================================================================

    def test_22_post_upload_a2_still_works_with_alias_route(self):
        """22. POST upload A2 vẫn hoạt động bình thường trên alias route /api/users/profile/avatar."""
        buf = _create_image_buffer(format="WEBP")
        headers = self._get_auth_headers()
        res = self.client.post(
            "/api/users/profile/avatar",
            data={"avatar": (buf, "alias_check.webp", "image/webp")},
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["avatar"]["path"].endswith(".webp"))

    def test_23_get_profile_reflects_avatar_lifecycle(self):
        """23. GET profile vẫn hoạt động bình thường, và DB phản ánh đúng trạng thái avatar sau upload và sau delete."""
        headers = self._get_auth_headers()

        # Ban đầu: None
        res_0 = self.client.get("/api/v1/users/profile", headers=headers)
        self.assertEqual(res_0.status_code, 200)
        self.assertEqual(res_0.get_json()["data"]["id"], self.user_a_id)
        user_0 = user_repository.get_user_by_id(self.user_a_id)
        self.assertIsNone(user_0.avatar_path)

        # Upload avatar mới
        upload_res = self._upload_avatar(format="PNG")
        self.assertEqual(upload_res.status_code, 200)
        uploaded_path = upload_res.get_json()["avatar"]["path"]

        res_1 = self.client.get("/api/v1/users/profile", headers=headers)
        self.assertEqual(res_1.status_code, 200)
        self.assertEqual(res_1.get_json()["data"]["name"], "Nguyễn Văn A")
        user_1 = user_repository.get_user_by_id(self.user_a_id)
        self.assertEqual(user_1.avatar_path, uploaded_path)

        # Delete avatar
        del_res = self.client.delete("/api/v1/users/profile/avatar", headers=headers)
        self.assertEqual(del_res.status_code, 200)

        res_2 = self.client.get("/api/v1/users/profile", headers=headers)
        self.assertEqual(res_2.status_code, 200)
        user_2 = user_repository.get_user_by_id(self.user_a_id)
        self.assertIsNone(user_2.avatar_path)

    def test_24_profile_update_scrum120_does_not_affect_avatar(self):
        """24. PUT profile update (SCRUM-120) không ghi đè hoặc làm mất avatar_path."""
        self._upload_avatar(format="JPEG")
        user_before = user_repository.get_user_by_id(self.user_a_id)
        original_avatar = user_before.avatar_path
        self.assertIsNotNone(original_avatar)

        # Cập nhật thông tin profile hợp lệ qua PUT (các trường được phép theo SCRUM-120: name, phone, address, date_of_birth)
        headers = self._get_auth_headers()
        put_res = self.client.put(
            "/api/v1/users/profile",
            json={
                "name": "Nguyễn Văn A Updated",
                "phone": "0987654321",
                "address": "Thái Nguyên",
                "date_of_birth": "2000-01-01",
            },
            headers=headers,
        )
        self.assertEqual(put_res.status_code, 200)

        # Avatar path phải được giữ nguyên hoàn toàn trong DB
        user_after = user_repository.get_user_by_id(self.user_a_id)
        self.assertEqual(user_after.avatar_path, original_avatar)
        self.assertEqual(user_after.name, "Nguyễn Văn A Updated")

    def test_25_delete_alias_route_works(self):
        """25. DELETE /api/users/profile/avatar (alias route) hoạt động chính xác tương tự /api/v1/..."""
        self._upload_avatar(format="JPEG")
        headers = self._get_auth_headers()
        res = self.client.delete("/api/users/profile/avatar", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

        user = user_repository.get_user_by_id(self.user_a_id)
        self.assertIsNone(user.avatar_path)


if __name__ == "__main__":
    unittest.main()
