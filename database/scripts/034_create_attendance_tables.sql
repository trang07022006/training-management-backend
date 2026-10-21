-- Migration 034: Bảng điểm danh buổi học và lịch sử chỉnh sửa điểm danh (SCRUM-254)
-- Hỗ trợ 4 trạng thái: Có mặt (present), Đi muộn (late), Vắng có phép (excused), Vắng không phép (unexcused)
-- Ghi nhận lịch sử mọi lần chỉnh sửa điểm danh để phục vụ kiểm toán và tính công khai

CREATE TABLE IF NOT EXISTS session_attendances (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    schedule_id VARCHAR(36) NOT NULL,
    student_id VARCHAR(36) NOT NULL,
    status VARCHAR(20) NOT NULL, -- 'present', 'late', 'excused', 'unexcused'
    notes TEXT NULL,
    recorded_by VARCHAR(36) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_session_attendance_schedule_student UNIQUE (schedule_id, student_id),
    INDEX idx_sa_schedule (schedule_id),
    INDEX idx_sa_student (student_id),
    INDEX idx_sa_status (status),
    CONSTRAINT fk_sa_schedule FOREIGN KEY (schedule_id) REFERENCES class_schedules(id) ON DELETE CASCADE,
    CONSTRAINT fk_sa_student FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE RESTRICT,
    CONSTRAINT fk_sa_recorded_by FOREIGN KEY (recorded_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS attendance_audit_logs (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    schedule_id VARCHAR(36) NOT NULL,
    student_id VARCHAR(36) NOT NULL,
    old_status VARCHAR(20) NULL,
    new_status VARCHAR(20) NOT NULL,
    reason TEXT NULL,
    performed_by VARCHAR(36) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_aal_schedule (schedule_id),
    INDEX idx_aal_student (student_id),
    INDEX idx_aal_performed_by (performed_by),
    INDEX idx_aal_created_at (created_at),
    CONSTRAINT fk_aal_schedule FOREIGN KEY (schedule_id) REFERENCES class_schedules(id) ON DELETE CASCADE,
    CONSTRAINT fk_aal_student FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE RESTRICT,
    CONSTRAINT fk_aal_performed_by FOREIGN KEY (performed_by) REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Bổ sung quyền hạn điểm danh buổi học
INSERT INTO permissions (id, code, name, description, created_at, updated_at)
VALUES 
    ('perm-id-attendance-view', 'attendance.view', 'Xem điểm danh buổi học', 'Xem sổ điểm danh và kết quả điểm danh của buổi học', NOW(), NOW()),
    ('perm-id-attendance-take', 'attendance.take', 'Điểm danh buổi học', 'Thực hiện điểm danh học viên cho buổi học được phân công', NOW(), NOW()),
    ('perm-id-attendance-manage', 'attendance.manage', 'Quản lý điểm danh buổi học', 'Quản lý và chỉnh sửa điểm danh các buổi học bao gồm cả buổi quá khứ', NOW(), NOW())
ON DUPLICATE KEY UPDATE 
    name = VALUES(name),
    description = VALUES(description),
    updated_at = NOW();

-- Phân quyền cho vai trò:
-- Giảng viên (trainer): attendance.view, attendance.take
-- Quản lý đào tạo (training_manager): attendance.view, attendance.take, attendance.manage
-- Quản trị viên (admin): Không tự động có quyền nghiệp vụ đào tạo
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-trainer', 'perm-id-attendance-view', NOW()),
    ('role-id-trainer', 'perm-id-attendance-take', NOW()),
    ('role-id-training-manager', 'perm-id-attendance-view', NOW()),
    ('role-id-training-manager', 'perm-id-attendance-take', NOW()),
    ('role-id-training-manager', 'perm-id-attendance-manage', NOW());
