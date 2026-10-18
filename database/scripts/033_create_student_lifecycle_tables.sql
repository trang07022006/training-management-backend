-- Migration 033: Bảng lịch sử vòng đời học viên và trường mở rộng cho class_enrollments (SCRUM-252)
-- Hỗ trợ 3 nghiệp vụ: Bảo lưu (reserve), Chuyển lớp (transfer), Thôi học (drop)
-- Bảo đảm ghi nhận lý do bắt buộc, ngày hiệu lực và người thực hiện

-- 1. Bổ sung các cột mở rộng cho bảng class_enrollments nếu chưa có
SET @dbname = DATABASE();

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS 
    WHERE TABLE_SCHEMA = @dbname AND TABLE_NAME = 'class_enrollments' AND COLUMN_NAME = 'lifecycle_status'
);
SET @sql = IF(@col_exists = 0, 'ALTER TABLE class_enrollments ADD COLUMN lifecycle_status VARCHAR(50) NULL AFTER status', 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS 
    WHERE TABLE_SCHEMA = @dbname AND TABLE_NAME = 'class_enrollments' AND COLUMN_NAME = 'effective_date'
);
SET @sql = IF(@col_exists = 0, 'ALTER TABLE class_enrollments ADD COLUMN effective_date DATE NULL AFTER lifecycle_status', 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS 
    WHERE TABLE_SCHEMA = @dbname AND TABLE_NAME = 'class_enrollments' AND COLUMN_NAME = 'lifecycle_reason'
);
SET @sql = IF(@col_exists = 0, 'ALTER TABLE class_enrollments ADD COLUMN lifecycle_reason TEXT NULL AFTER effective_date', 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 2. Tạo bảng lưu trữ lịch sử thay đổi vòng đời học viên (student_lifecycle_history)
CREATE TABLE IF NOT EXISTS student_lifecycle_history (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    student_id VARCHAR(36) NOT NULL,
    enrollment_id VARCHAR(36) NULL,
    action_type VARCHAR(50) NOT NULL, -- 'reserve', 'transfer', 'drop'
    source_class_id VARCHAR(36) NULL,
    target_class_id VARCHAR(36) NULL,
    effective_date DATE NOT NULL,
    reason TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'applied', -- 'pending' hoặc 'applied'
    performed_by VARCHAR(36) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_slh_student (student_id),
    INDEX idx_slh_action (action_type),
    INDEX idx_slh_effective_date (effective_date),
    INDEX idx_slh_source_class (source_class_id),
    INDEX idx_slh_target_class (target_class_id),
    CONSTRAINT fk_slh_student FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE RESTRICT,
    CONSTRAINT fk_slh_performer FOREIGN KEY (performed_by) REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Bổ sung quyền hạn chuyên biệt cho Quản lý đào tạo (SCRUM-252)
INSERT INTO permissions (id, code, name, description, created_at, updated_at)
VALUES 
    ('perm-id-student-lifecycle-manage', 'student.lifecycle_manage', 'Quản lý vòng đời học viên', 'Xử lý bảo lưu, chuyển lớp và thôi học của học viên', NOW(), NOW())
ON DUPLICATE KEY UPDATE 
    name = VALUES(name),
    description = VALUES(description),
    updated_at = NOW();

-- Gán quyền cho Quản lý đào tạo (training_manager), không cấp cho admin thuần túy
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-training-manager', 'perm-id-student-lifecycle-manage', NOW());
