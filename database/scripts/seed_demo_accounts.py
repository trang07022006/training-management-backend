"""Script khởi tạo schema và các tài khoản demo (Admin, Trainer, Trainee) cho Sprint 1.
Chạy script này một cách an toàn (idempotent), không phá hủy dữ liệu cũ.
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

# Đảm bảo import được các module của app
backend_dir = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_dir))
load_dotenv(backend_dir / ".env")

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.database.connection import get_db_connection
from app.services.rbac_service import sync_business_rbac_data, sync_initial_rbac_data

# Mật khẩu demo chuẩn hóa tuân thủ chính sách: >= 8 ký tự, có chữ và số
DEMO_PASSWORD_DEFAULT = "Demo@123456"

DEMO_ACCOUNTS = [
    {
        "id": "demo-user-admin",
        "email": "admin.demo@daotao.edu.vn",
        "name": "Quản trị viên Demo",
        "phone": "0988000001",
        "role_code": "admin",
        "role_id": "role-id-admin",
        "status": "active",
    },
    {
        "id": "demo-user-trainer",
        "email": "trainer.demo@daotao.edu.vn",
        "name": "Giảng viên Demo",
        "phone": "0988000002",
        "role_code": "trainer",
        "role_id": "role-id-trainer",
        "status": "active",
    },
    {
        "id": "demo-user-trainee",
        "email": "trainee.demo@daotao.edu.vn",
        "name": "Học viên Demo",
        "phone": "0988000003",
        "role_code": "trainee",
        "role_id": "role-id-trainee",
        "status": "active",
    },
    {
        "id": "demo-user-locked",
        "email": "locked.demo@daotao.edu.vn",
        "name": "Tài khoản Khóa Demo",
        "phone": "0988000004",
        "role_code": "user",
        "role_id": "role-id-user",
        "status": "inactive",
    },
]

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id VARCHAR(36) PRIMARY KEY,
        email VARCHAR(255) NOT NULL UNIQUE,
        name VARCHAR(255) NULL,
        phone VARCHAR(50) NULL,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(50) NOT NULL DEFAULT 'user',
        status VARCHAR(50) NOT NULL DEFAULT 'active',
        failed_login_attempts INT NOT NULL DEFAULT 0,
        locked_until DATETIME NULL DEFAULT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS roles (
        id VARCHAR(50) PRIMARY KEY,
        code VARCHAR(50) NOT NULL UNIQUE,
        name VARCHAR(100) NOT NULL,
        description TEXT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS permissions (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        code VARCHAR(100) NOT NULL UNIQUE,
        name VARCHAR(100) NOT NULL,
        description VARCHAR(255) NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        INDEX idx_permissions_code (code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS role_permissions (
        role_id VARCHAR(36) NOT NULL,
        permission_id VARCHAR(36) NOT NULL,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (role_id, permission_id),
        CONSTRAINT fk_role_permissions_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
        CONSTRAINT fk_role_permissions_permission FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE,
        INDEX idx_rp_permission_id (permission_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS user_roles (
        user_id VARCHAR(64) NOT NULL,
        role_id VARCHAR(36) NOT NULL,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (user_id, role_id),
        CONSTRAINT fk_user_roles_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
        INDEX idx_ur_role_id (role_id),
        INDEX idx_ur_user_id (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_sessions (
        session_id VARCHAR(64) PRIMARY KEY,
        user_id VARCHAR(36) NOT NULL,
        refresh_jti VARCHAR(64) NOT NULL,
        created_at DATETIME NOT NULL,
        last_activity_at DATETIME NOT NULL,
        idle_expires_at DATETIME NOT NULL,
        absolute_expires_at DATETIME NOT NULL,
        revoked_at DATETIME NULL DEFAULT NULL,
        INDEX idx_auth_sessions_user_id (user_id),
        CONSTRAINT fk_auth_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id VARCHAR(36) PRIMARY KEY,
        user_id VARCHAR(36) NOT NULL,
        token_hash VARCHAR(64) NOT NULL UNIQUE,
        expires_at DATETIME NOT NULL,
        used_at DATETIME NULL DEFAULT NULL,
        created_at DATETIME NOT NULL,
        INDEX idx_prt_user_id (user_id),
        INDEX idx_prt_token_hash (token_hash),
        CONSTRAINT fk_prt_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
]


def ensure_schema(connection):
    with connection.cursor() as cursor:
        for statement in DDL_STATEMENTS:
            cursor.execute(statement.strip())
        connection.commit()
    print("✓ Đã đảm bảo schema cơ sở dữ liệu hoàn chỉnh.")


def seed_demo_users(connection, password=DEMO_PASSWORD_DEFAULT):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    hashed = generate_password_hash(password)

    with connection.cursor(dictionary=True) as cursor:
        for acc in DEMO_ACCOUNTS:
            # Kiểm tra xem user đã tồn tại chưa
            cursor.execute("SELECT id, email, role, status FROM users WHERE email = %s", (acc["email"],))
            existing = cursor.fetchone()

            if existing:
                user_id = existing["id"]
                # Cập nhật thông tin và mật khẩu demo
                cursor.execute(
                    """
                    UPDATE users
                    SET password_hash = %s, role = %s, status = %s, name = %s, phone = %s, failed_login_attempts = 0, locked_until = NULL, updated_at = %s
                    WHERE id = %s
                    """,
                    (hashed, acc["role_code"], acc["status"], acc["name"], acc["phone"], now, user_id),
                )
                print(f"✓ Cập nhật tài khoản demo: {acc['email']} (Role: {acc['role_code']}, Status: {acc['status']})")
            else:
                user_id = acc["id"]
                cursor.execute(
                    """
                    INSERT INTO users (id, email, name, phone, password_hash, role, status, failed_login_attempts, locked_until, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 0, NULL, %s, %s)
                    """,
                    (user_id, acc["email"], acc["name"], acc["phone"], hashed, acc["role_code"], acc["status"], now, now),
                )
                print(f"✓ Tạo mới tài khoản demo: {acc['email']} (Role: {acc['role_code']}, Status: {acc['status']})")

            # Gán vào bảng user_roles (idempotent)
            cursor.execute(
                """
                INSERT IGNORE INTO user_roles (user_id, role_id, created_at)
                VALUES (%s, %s, %s)
                """,
                (user_id, acc["role_id"], now),
            )

        connection.commit()


def main():
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"✗ Không thể kết nối tới MySQL: {e}")
        print("Vui lòng kiểm tra cấu hình DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD trong backend/.env")
        sys.exit(1)

    try:
        print("Đang khởi tạo schema...")
        ensure_schema(conn)

        print("Đang đồng bộ dữ liệu RBAC (Roles, Permissions, Mappings)...")
        rbac_result = sync_initial_rbac_data()
        business_rbac_result = sync_business_rbac_data()
        print(f"✓ RBAC sync: {rbac_result}, business: {business_rbac_result}")

        print("Đang seed tài khoản demo...")
        seed_demo_users(conn)

        print("\n=== HOÀN TẤT SEED DEMO ACCOUNTS ===")
        print("Các tài khoản sẵn sàng sử dụng:")
        for acc in DEMO_ACCOUNTS:
            print(f"- Email: {acc['email']} | Vai trò: {acc['role_code']} | Trạng thái: {acc['status']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
