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
            # 4. SCRUM-213: Bổ sung bảng lead_status_history và trường rejection_reason
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS lead_status_history (
                    id VARCHAR(36) PRIMARY KEY,
                    lead_id VARCHAR(36) NOT NULL,
                    old_status VARCHAR(50) NOT NULL,
                    new_status VARCHAR(50) NOT NULL,
                    reason VARCHAR(255) NULL,
                    notes TEXT NULL,
                    performed_by_user_id VARCHAR(36) NULL,
                    created_at DATETIME NOT NULL,
                    seq BIGINT AUTO_INCREMENT UNIQUE,
                    CONSTRAINT fk_lsh_lead FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
                    CONSTRAINT fk_lsh_performed_user FOREIGN KEY (performed_by_user_id) REFERENCES users(id) ON DELETE SET NULL
                );
            """)

            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.statistics 
                WHERE table_schema = DATABASE() AND table_name = 'lead_status_history' AND index_name = 'idx_lsh_lead_id';
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("CREATE INDEX idx_lsh_lead_id ON lead_status_history (lead_id);")

            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.statistics 
                WHERE table_schema = DATABASE() AND table_name = 'lead_status_history' AND index_name = 'idx_lsh_created_at';
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("CREATE INDEX idx_lsh_created_at ON lead_status_history (created_at);")

            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_schema = DATABASE() AND table_name = 'leads' AND column_name = 'rejection_reason';
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("ALTER TABLE leads ADD COLUMN rejection_reason VARCHAR(255) NULL AFTER status;")

            # 5. SCRUM-214: Bổ sung bảng lead_care_logs và trường callback_date
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS lead_care_logs (
                    id VARCHAR(36) PRIMARY KEY,
                    lead_id VARCHAR(36) NOT NULL,
                    interaction_type VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    interaction_at DATETIME NOT NULL,
                    performed_by_user_id VARCHAR(36) NULL,
                    created_at DATETIME NOT NULL,
                    seq BIGINT AUTO_INCREMENT UNIQUE,
                    CONSTRAINT fk_lcl_lead FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
                    CONSTRAINT fk_lcl_performed_user FOREIGN KEY (performed_by_user_id) REFERENCES users(id) ON DELETE SET NULL
                );
            """)

            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.statistics 
                WHERE table_schema = DATABASE() AND table_name = 'lead_care_logs' AND index_name = 'idx_lcl_lead_id';
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("CREATE INDEX idx_lcl_lead_id ON lead_care_logs (lead_id);")

            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.statistics 
                WHERE table_schema = DATABASE() AND table_name = 'lead_care_logs' AND index_name = 'idx_lcl_interaction_at';
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("CREATE INDEX idx_lcl_interaction_at ON lead_care_logs (interaction_at);")

            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_schema = DATABASE() AND table_name = 'leads' AND column_name = 'callback_date';
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("ALTER TABLE leads ADD COLUMN callback_date DATE NULL AFTER rejection_reason;")

            connection.commit()
        connection.close()
        logger.info("✓ Business roles, permissions, lead status history and care logs schema ensured successfully.")
    except Exception as e:
        logger.warning("Could not auto-ensure business roles and schema: %s", e)
