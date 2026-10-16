import logging

from app.database.connection import get_db_connection

logger = logging.getLogger(__name__)


def ensure_business_roles() -> None:
    """Synchronize business roles and permissions after the SQL migrations run.

    Schema creation belongs to the ordered SQL migrations in ``database/scripts``.
    Keeping DDL out of this startup data synchronizer avoids creating tables with
    missing prerequisites (for example, lead history before ``leads`` exists).
    """
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO roles (id, code, name, description, created_at, updated_at)
                VALUES
                    ('role-id-consultant', 'consultant', 'Tư vấn tuyển sinh',
                     'Tư vấn tuyển sinh và quản lý khách hàng tiềm năng', NOW(), NOW()),
                    ('role-id-training-manager', 'training_manager', 'Quản lý đào tạo',
                     'Quản lý chương trình đào tạo và khách hàng tiềm năng', NOW(), NOW())
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    description = VALUES(description),
                    updated_at = NOW()
                """
            )
            cursor.execute(
                """
                INSERT INTO permissions (id, code, name, description, created_at, updated_at)
                VALUES ('perm-id-lead-delete', 'lead.delete', 'Xóa khách hàng tiềm năng',
                        'Quyền xóa khách hàng tiềm năng trong hệ thống', NOW(), NOW())
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    description = VALUES(description),
                    updated_at = NOW()
                """
            )
            cursor.execute(
                """
                INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
                VALUES
                    ('role-id-training-manager', 'perm-id-course-view', NOW()),
                    ('role-id-training-manager', 'perm-id-course-manage', NOW()),
                    ('role-id-training-manager', 'perm-id-session-view', NOW()),
                    ('role-id-training-manager', 'perm-id-lead-delete', NOW()),
                    ('role-id-consultant', 'perm-id-course-view', NOW()),
                    ('role-id-consultant', 'perm-id-course-manage', NOW()),
                    ('role-id-admin', 'perm-id-lead-delete', NOW());
            """)

            # 3.5 Bổ sung Permissions và Mapping cho phân hệ Thời khóa biểu (SCRUM-228)
            cursor.execute("""
                INSERT INTO permissions (id, code, name, description, created_at, updated_at)
                VALUES 
                    ('perm-id-schedule-view', 'schedule.view', 'Xem thời khóa biểu', 'Xem thời khóa biểu và lịch giảng dạy/học tập toàn trường', NOW(), NOW()),
                    ('perm-id-schedule-manage', 'schedule.manage', 'Quản lý thời khóa biểu', 'Tạo, sửa, hủy và điều chỉnh lịch học, thời khóa biểu', NOW(), NOW()),
                    ('perm-id-schedule-personal-view', 'schedule.personal_view', 'Xem lịch cá nhân', 'Xem thời khóa biểu cá nhân của học viên hoặc lịch giảng dạy của giảng viên', NOW(), NOW())
                ON DUPLICATE KEY UPDATE 
                    name = VALUES(name),
                    description = VALUES(description),
                    updated_at = NOW();
            """)

            cursor.execute("""
                INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
                VALUES 
                    ('role-id-admin', 'perm-id-schedule-view', NOW()),
                    ('role-id-admin', 'perm-id-schedule-manage', NOW()),
                    ('role-id-training-manager', 'perm-id-schedule-view', NOW()),
                    ('role-id-training-manager', 'perm-id-schedule-manage', NOW()),
                    ('role-id-trainer', 'perm-id-schedule-view', NOW()),
                    ('role-id-trainer', 'perm-id-schedule-personal-view', NOW()),
                    ('role-id-trainee', 'perm-id-schedule-personal-view', NOW());
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

            # 6. SCRUM-215: Đảm bảo bảng students và bảng sequence
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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS student_code_sequences (
                    prefix VARCHAR(20) NOT NULL PRIMARY KEY,
                    current_val INT UNSIGNED NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

            # 7. SCRUM-215 Initial Password Change Request: Cột must_change_password trong bảng users
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_schema = DATABASE() AND table_name = 'users' AND column_name = 'must_change_password';
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE AFTER failed_login_attempts;")

            # 8. SCRUM-216: Cột entry_level và notes trong bảng students
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_schema = DATABASE() AND table_name = 'students' AND column_name = 'entry_level';
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("ALTER TABLE students ADD COLUMN entry_level VARCHAR(255) NULL AFTER status;")

            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_schema = DATABASE() AND table_name = 'students' AND column_name = 'notes';
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("ALTER TABLE students ADD COLUMN notes TEXT NULL AFTER entry_level;")

            # 9. SCRUM-217: Bảng classes và class_subjects
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS classes (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    class_code VARCHAR(50) NOT NULL UNIQUE,
                    program_id VARCHAR(36) NOT NULL,
                    expected_start_date DATE NULL,
                    max_capacity INT UNSIGNED NOT NULL DEFAULT 30,
                    learning_mode VARCHAR(50) NOT NULL DEFAULT 'offline',
                    status VARCHAR(50) NOT NULL DEFAULT 'preparing',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    INDEX idx_classes_program_id (program_id),
                    INDEX idx_classes_status (status),
                    INDEX idx_classes_class_code (class_code)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS class_subjects (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    class_id VARCHAR(36) NOT NULL,
                    subject_id VARCHAR(36) NOT NULL,
                    semester SMALLINT UNSIGNED NULL,
                    is_mandatory BOOLEAN NOT NULL DEFAULT TRUE,
                    order_index SMALLINT UNSIGNED NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    UNIQUE KEY uq_class_subjects (class_id, subject_id),
                    INDEX idx_class_subjects_class (class_id),
                    INDEX idx_class_subjects_subject (subject_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

            # 10. SCRUM-218: Bảng class_enrollments
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS class_enrollments (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    class_id VARCHAR(36) NOT NULL,
                    student_id VARCHAR(36) NOT NULL,
                    status VARCHAR(50) NOT NULL DEFAULT 'enrolled',
                    enrolled_at DATETIME NOT NULL,
                    enrolled_by VARCHAR(36) NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    UNIQUE KEY uq_class_student (class_id, student_id),
                    INDEX idx_enrollments_class_id (class_id),
                    INDEX idx_enrollments_student_id (student_id),
                    INDEX idx_enrollments_enrolled_at (enrolled_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

            # 11. SCRUM-224: Bảng holidays và class_schedules
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS holidays (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    holiday_date DATE NOT NULL UNIQUE,
                    name VARCHAR(255) NOT NULL,
                    description TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_holidays_date (holiday_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS class_schedules (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    class_id VARCHAR(36) NOT NULL,
                    class_subject_id VARCHAR(36) NULL,
                    subject_id VARCHAR(36) NULL,
                    subject_session_id VARCHAR(36) NULL,
                    session_number INT NOT NULL,
                    topic VARCHAR(255) NOT NULL,
                    learning_date DATE NOT NULL,
                    shift VARCHAR(50) NULL,
                    start_time TIME NOT NULL,
                    end_time TIME NOT NULL,
                    room_id VARCHAR(36) NULL,
                    instructor_id VARCHAR(36) NULL,
                    status VARCHAR(50) NOT NULL DEFAULT 'scheduled',
                    cancellation_reason TEXT NULL,
                    attendance_checked BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_schedules_class_id (class_id),
                    INDEX idx_schedules_date (learning_date),
                    INDEX idx_schedules_room_time (room_id, learning_date, start_time, end_time),
                    INDEX idx_schedules_instructor_time (instructor_id, learning_date, start_time, end_time)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

            # 12. SCRUM-221: Bảng classrooms
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS classrooms (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    room_code VARCHAR(50) NOT NULL UNIQUE,
                    room_name VARCHAR(100) NOT NULL,
                    room_type VARCHAR(20) NOT NULL DEFAULT 'physical',
                    capacity INT NULL,
                    online_link TEXT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    INDEX idx_classrooms_type (room_type),
                    INDEX idx_classrooms_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

            # 13. SCRUM-220: Bảng class_subject_instructors
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS class_subject_instructors (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    class_subject_id VARCHAR(36) NOT NULL,
                    instructor_id VARCHAR(36) NOT NULL,
                    role_type VARCHAR(50) NOT NULL DEFAULT 'main',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    UNIQUE KEY uq_class_subject_instructor (class_subject_id, instructor_id),
                    INDEX idx_csi_class_subject (class_subject_id),
                    INDEX idx_csi_instructor (instructor_id),
                    INDEX idx_csi_role_type (role_type)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

            connection.commit()
        connection.close()
        logger.info("✓ Business roles, permissions, lead history, care logs, student schemas, class schemas, enrollments, holidays, class schedules, classrooms, and instructor assignments ensured successfully.")
    except Exception as e:
        logger.warning("Could not auto-ensure business roles and schemas: %s", e)
