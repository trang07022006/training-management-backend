"""
Bộ kiểm thử SCRUM-121 (Activity A1): Xây dựng nền tảng database và storage cho avatar người dùng.

Mục tiêu kiểm thử:
1. Model User và repository hỗ trợ trường avatar_path
2. Người dùng không có avatar -> avatar_path là None / NULL
3. Người dùng có avatar -> đọc đúng avatar_path từ database
4. Migration/schema không phá vỡ hồ sơ người dùng (SCRUM-120) hiện tại
5. Các serialization hiện tại tuyệt đối không làm lộ trường nhạy cảm
6. Cấu trúc thư mục storage uploads/avatars và .gitignore được thiết lập đúng
7. Cấu hình AVATAR_UPLOAD_FOLDER, AVATAR_MAX_FILE_SIZE = 2MB, và kiến trúc an ninh tên file
"""

import os
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.config.avatar_config import (
    ALLOWED_AVATAR_EXTENSIONS,
    AVATAR_MAX_FILE_SIZE,
    AVATAR_UPLOAD_FOLDER,
    FORBIDDEN_AVATAR_EXTENSIONS,
    configure_avatar,
    generate_avatar_filename,
    is_allowed_avatar_extension,
    is_safe_avatar_path,
)
from app.config.jwt_handlers import register_jwt_handlers
from app.database.connection import get_db_connection
from app.models.login_session import LoginSession
from app.models.user import User
from app.repositories import session_repository, user_repository
from app.routes.user_routes import user_bp


class Scrum121AvatarFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend_dir = Path(__file__).resolve().parents[1]

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum121-suite-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        configure_avatar(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()

    # =========================================================================
    # 1. USER MODEL & REPOSITORY MAPPING
    # =========================================================================

    def test_01_user_model_supports_avatar_path_default_none(self):
        """User model hỗ trợ avatar_path và mặc định là None khi chưa có ảnh."""
        u = User(id="user-no-avatar", email="noavatar@daotao.edu.vn")
        self.assertIsNone(u.avatar_path)

    def test_02_user_model_supports_avatar_path_assignment(self):
        """User model có thể lưu trữ avatar_path dạng relative path."""
        relative_path = "avatars/550e8400-e29b-41d4-a716-446655440000.webp"
        u = User(
            id="user-has-avatar",
            email="avatar@daotao.edu.vn",
            avatar_path=relative_path,
        )
        self.assertEqual(u.avatar_path, relative_path)

    def test_03_repository_row_to_user_maps_avatar_path(self):
        """_row_to_user nạp đúng avatar_path từ database row (cả khi NULL và khi có giá trị)."""
        # Case 1: NULL
        row_null = {
            "id": "u-1",
            "email": "null@daotao.vn",
            "password_hash": "hash",
            "avatar_path": None,
        }
        user_null = user_repository._row_to_user(row_null)
        self.assertIsNone(user_null.avatar_path)

        # Case 2: Has avatar path
        avatar_file = "avatars/c3d80312-d021-4f10-9112-704975d04589.png"
        row_with_avatar = {
            "id": "u-2",
            "email": "avatar@daotao.vn",
            "password_hash": "hash",
            "avatar_path": avatar_file,
        }
        user_with_avatar = user_repository._row_to_user(row_with_avatar)
        self.assertEqual(user_with_avatar.avatar_path, avatar_file)

    # =========================================================================
    # 2. DATABASE SCHEMA & PERSISTENCE
    # =========================================================================

    def test_04_database_schema_has_avatar_path_column(self):
        """Kiểm tra cột avatar_path tồn tại trong bảng users MySQL với đúng kiểu VARCHAR(255) NULL."""
        conn = get_db_connection()
        try:
            with conn.cursor(dictionary=True) as cur:
                cur.execute("DESCRIBE users")
                cols = cur.fetchall()
                avatar_col = next((c for c in cols if c["Field"] == "avatar_path"), None)
                self.assertIsNotNone(avatar_col, "Cột avatar_path chưa tồn tại trong bảng users")
                self.assertEqual(avatar_col["Null"], "YES", "Cột avatar_path phải cho phép NULL")
                self.assertIn("varchar(255)", avatar_col["Type"].lower())
        finally:
            conn.close()

    def test_05_database_read_user_with_and_without_avatar(self):
        """Kiểm tra repository SELECT đọc chính xác avatar_path từ MySQL."""
        test_user_id = f"test-avatar-{int(datetime.now().timestamp())}"
        test_email = f"{test_user_id}@daotao.edu.vn"
        avatar_val = f"avatars/{test_user_id}.webp"

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, email, password_hash, role, status, avatar_path)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (test_user_id, test_email, "hash123", "user", "active", None),
                )
            conn.commit()

            # 1. Đọc khi avatar_path là NULL
            u1 = user_repository.get_user_by_id(test_user_id)
            self.assertIsNotNone(u1)
            self.assertIsNone(u1.avatar_path)

            u1_email = user_repository.get_user_by_email(test_email)
            self.assertIsNotNone(u1_email)
            self.assertIsNone(u1_email.avatar_path)

            # 2. Cập nhật avatar_path vào DB và đọc lại
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET avatar_path = %s WHERE id = %s",
                    (avatar_val, test_user_id),
                )
            conn.commit()

            u2 = user_repository.get_user_by_id(test_user_id)
            self.assertIsNotNone(u2)
            self.assertEqual(u2.avatar_path, avatar_val)

            u2_email = user_repository.get_user_by_email(test_email)
            self.assertIsNotNone(u2_email)
            self.assertEqual(u2_email.avatar_path, avatar_val)

        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s", (test_user_id,))
            conn.commit()
            conn.close()

    # =========================================================================
    # 3. PROFILE SERIALIZATION & SECURITY
    # =========================================================================

    def test_06_profile_serialization_backwards_compatible(self):
        """to_profile_dict() giữ nguyên hợp đồng SCRUM-120 mặc định, và có thể bao gồm avatar_path khi yêu cầu."""
        u = User(
            id="u-profile-test",
            name="Nguyễn Văn Test",
            email="test@daotao.edu.vn",
            phone="0912345678",
            date_of_birth=date(1996, 4, 10),
            address="Thái Nguyên",
            role="trainee",
            avatar_path="avatars/test-avatar.webp",
        )

        # Mặc định (A1): giữ nguyên cấu trúc SCRUM-120, không phá vỡ public contract
        default_dict = u.to_profile_dict()
        self.assertEqual(default_dict["id"], "u-profile-test")
        self.assertEqual(default_dict["name"], "Nguyễn Văn Test")
        self.assertEqual(default_dict["email"], "test@daotao.edu.vn")
        self.assertEqual(default_dict["phone"], "0912345678")
        self.assertEqual(default_dict["date_of_birth"], "1996-04-10")
        self.assertEqual(default_dict["address"], "Thái Nguyên")
        self.assertEqual(default_dict["role"], "trainee")

        # Khi cần bao gồm avatar (chuẩn bị cho slice sau)
        extended_dict = u.to_profile_dict(include_avatar=True)
        self.assertEqual(extended_dict["avatar_path"], "avatars/test-avatar.webp")

    def test_07_serialization_does_not_leak_sensitive_fields(self):
        """Tuyệt đối không rò rỉ password_hash, lockout hay session data qua profile dict hoặc public dict."""
        u = User(
            id="u-sec",
            email="sec@daotao.vn",
            password_hash="pbkdf2:sha256:600000$supersecret$hash",
            failed_login_attempts=3,
            locked_until=datetime.now(timezone.utc),
            avatar_path="avatars/sec.jpg",
        )
        p_dict = u.to_profile_dict()
        pub_dict = u.to_public_dict()

        for d in (p_dict, pub_dict):
            self.assertNotIn("password", d)
            self.assertNotIn("password_hash", d)
            self.assertNotIn("failed_login_attempts", d)
            self.assertNotIn("locked_until", d)
            self.assertNotIn("session_id", d)

    # =========================================================================
    # 4. STORAGE STRUCTURE & GITIGNORE
    # =========================================================================

    def test_08_storage_structure_uploads_avatars_exists(self):
        """Thư mục uploads/avatars tồn tại và chứa file .gitkeep để theo dõi thư mục."""
        avatars_dir = self.backend_dir / "uploads" / "avatars"
        self.assertTrue(avatars_dir.exists(), "Thư mục uploads/avatars phải tồn tại")
        self.assertTrue(avatars_dir.is_dir(), "uploads/avatars phải là thư mục")

        gitkeep_file = avatars_dir / ".gitkeep"
        self.assertTrue(gitkeep_file.exists(), ".gitkeep phải tồn tại trong uploads/avatars")

    def test_09_gitignore_ignores_runtime_avatar_uploads(self):
        """File .gitignore loại trừ file upload runtime trong uploads/avatars/* và giữ .gitkeep."""
        gitignore_path = self.backend_dir / ".gitignore"
        self.assertTrue(gitignore_path.exists())
        content = gitignore_path.read_text(encoding="utf-8")

        self.assertIn("uploads/avatars/*", content)
        self.assertIn("!uploads/avatars/.gitkeep", content)

    # =========================================================================
    # 5. CONFIGURATION & SECURITY ARCHITECTURE
    # =========================================================================

    def test_10_avatar_configuration_values(self):
        """Kiểm tra cấu hình AVATAR_MAX_FILE_SIZE = 2MB và các định dạng được phép."""
        self.assertEqual(AVATAR_MAX_FILE_SIZE, 2 * 1024 * 1024)
        self.assertEqual(ALLOWED_AVATAR_EXTENSIONS, {"jpg", "jpeg", "png", "webp"})

        # Flask app config
        self.assertEqual(self.app.config["AVATAR_MAX_FILE_SIZE"], 2 * 1024 * 1024)
        self.assertIn("uploads", self.app.config["AVATAR_UPLOAD_FOLDER"])
        self.assertEqual(self.app.config["ALLOWED_AVATAR_EXTENSIONS"], {"jpg", "jpeg", "png", "webp"})

    def test_11_avatar_security_extension_whitelist(self):
        """Kiểm tra danh sách trắng định dạng ảnh: cho phép jpg, jpeg, png, webp; cấm tuyệt đối SVG/HTML/executable."""
        self.assertTrue(is_allowed_avatar_extension("avatar.jpg"))
        self.assertTrue(is_allowed_avatar_extension("PHOTO.JPEG"))
        self.assertTrue(is_allowed_avatar_extension("image.png"))
        self.assertTrue(is_allowed_avatar_extension("user.webp"))

        # Cấm
        self.assertFalse(is_allowed_avatar_extension("bad.svg"))
        self.assertFalse(is_allowed_avatar_extension("hack.html"))
        self.assertFalse(is_allowed_avatar_extension("exploit.php"))
        self.assertFalse(is_allowed_avatar_extension("payload.exe"))
        self.assertFalse(is_allowed_avatar_extension("script.js"))
        self.assertFalse(is_allowed_avatar_extension(""))

    def test_12_avatar_security_random_uuid_filename_generation(self):
        """Sinh tên file ngẫu nhiên bằng UUIDv4, không bao giờ dùng tên gốc của user."""
        filename = generate_avatar_filename("webp")
        self.assertTrue(filename.endswith(".webp"))
        name_part = filename.rsplit(".", 1)[0]
        # UUID length 36 (32 hex + 4 dashes)
        self.assertEqual(len(name_part), 36)

        # Định dạng không hợp lệ phải ném ValueError
        with self.assertRaises(ValueError):
            generate_avatar_filename("svg")

    def test_13_avatar_security_path_traversal_prevention(self):
        """Ngăn chặn path traversal: kiểm tra đường dẫn an toàn nằm trong base folder."""
        base_dir = str(self.backend_dir / "uploads" / "avatars")
        safe_path = str(self.backend_dir / "uploads" / "avatars" / "random-uuid.webp")
        unsafe_path = str(self.backend_dir / "uploads" / "avatars" / ".." / ".." / "etc" / "passwd")

        self.assertTrue(is_safe_avatar_path(base_dir, safe_path))
        self.assertFalse(is_safe_avatar_path(base_dir, unsafe_path))


if __name__ == "__main__":
    unittest.main()
