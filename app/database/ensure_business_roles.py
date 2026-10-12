import logging
from app.database.connection import get_db_connection

logger = logging.getLogger(__name__)


def ensure_business_roles() -> None:
    """
    Tự động đồng bộ các vai trò nghiệp vụ (Tư vấn tuyển sinh, Quản lý đào tạo)
    và quyền xóa Lead (lead.delete) vào cơ sở dữ liệu nếu chưa có.
    Đảm bảo tính idempotent và an toàn khi khởi động máy chủ hoặc môi trường phát triển mới.
    """
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # 1. Bổ sung Roles
            cursor.execute("""
                INSERT INTO roles (id, code, name, description, created_at, updated_at)
                VALUES 
                    ('role-id-consultant', 'consultant', 'Tư vấn tuyển sinh', 'Tư vấn tuyển sinh và quản lý khách hàng tiềm năng', NOW(), NOW()),
                    ('role-id-training-manager', 'training_manager', 'Quản lý đào tạo', 'Quản lý chương trình đào tạo và khách hàng tiềm năng', NOW(), NOW())
                ON DUPLICATE KEY UPDATE 
                    name = VALUES(name),
                    description = VALUES(description),
                    updated_at = NOW();
            """)

            # 2. Bổ sung Permission lead.delete
            cursor.execute("""
                INSERT INTO permissions (id, code, name, description, created_at, updated_at)
                VALUES 
                    ('perm-id-lead-delete', 'lead.delete', 'Xóa khách hàng tiềm năng', 'Quyền xóa khách hàng tiềm năng trong hệ thống (chỉ dành cho Quản lý đào tạo)', NOW(), NOW())
                ON DUPLICATE KEY UPDATE 
                    name = VALUES(name),
                    description = VALUES(description),
                    updated_at = NOW();
            """)

            # 3. Gán Role Permissions
            cursor.execute("""
                INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
                VALUES 
                    ('role-id-training-manager', 'perm-id-course-view', NOW()),
                    ('role-id-training-manager', 'perm-id-course-manage', NOW()),
                    ('role-id-training-manager', 'perm-id-session-view', NOW()),
                    ('role-id-training-manager', 'perm-id-lead-delete', NOW()),
                    ('role-id-consultant', 'perm-id-course-view', NOW()),
                    ('role-id-consultant', 'perm-id-course-manage', NOW()),
                    ('role-id-consultant', 'perm-id-session-view', NOW()),
                    ('role-id-admin', 'perm-id-lead-delete', NOW());
            """)
            # 4. Đảm bảo bảng students (SCRUM-215)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS students (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    student_code VARCHAR(50) NOT NULL,
                    user_id VARCHAR(36) NULL,
                    lead_id VARCHAR(36) NULL,
                    full_name VARCHAR(255) NOT NULL,
                    phone VARCHAR(50) NOT NULL,
                    email VARCHAR(255) NULL,
                    program_id VARCHAR(36) NULL,
                    status VARCHAR(50) NOT NULL DEFAULT 'enrolled',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    CONSTRAINT uq_students_student_code UNIQUE (student_code),
                    CONSTRAINT uq_students_lead_id UNIQUE (lead_id),
                    CONSTRAINT uq_students_user_id UNIQUE (user_id),
                    CONSTRAINT fk_students_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
                    CONSTRAINT fk_students_lead FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE SET NULL,
                    CONSTRAINT fk_students_program FOREIGN KEY (program_id) REFERENCES training_programs(id) ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
            connection.commit()
        connection.close()
        logger.info("✓ Business roles and permissions ensured successfully.")
    except Exception as e:
        logger.warning("Could not auto-ensure business roles: %s", e)
