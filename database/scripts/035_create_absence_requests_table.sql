-- Migration 035: Bảng đơn xin phép vắng và đính kèm minh chứng (SCRUM-255)
-- Cho phép học viên gửi đơn xin phép vắng cho buổi học hợp lệ, theo dõi trạng thái
-- Giảng viên và Quản lý đào tạo xem xét, phê duyệt hoặc từ chối đơn

CREATE TABLE IF NOT EXISTS absence_requests (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    schedule_id VARCHAR(36) NOT NULL,
    student_id VARCHAR(36) NOT NULL,
    reason TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
    reviewed_by VARCHAR(36) NULL,
    reviewed_at DATETIME(6) NULL,
    rejection_reason TEXT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_ar_schedule (schedule_id),
    INDEX idx_ar_student (student_id),
    INDEX idx_ar_status (status),
    INDEX idx_ar_created_at (created_at),
    CONSTRAINT fk_ar_schedule FOREIGN KEY (schedule_id) REFERENCES class_schedules(id) ON DELETE CASCADE,
    CONSTRAINT fk_ar_student FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE RESTRICT,
    CONSTRAINT fk_ar_reviewed_by FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS absence_request_attachments (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    request_id VARCHAR(36) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size INT NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_ara_request (request_id),
    CONSTRAINT fk_ara_request FOREIGN KEY (request_id) REFERENCES absence_requests(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Bổ sung quyền hạn đơn xin phép vắng
INSERT INTO permissions (id, code, name, description, created_at, updated_at)
VALUES 
    ('perm-id-absence-request', 'absence.request', 'Gửi và xem đơn xin phép vắng', 'Học viên gửi đơn xin phép vắng và theo dõi kết quả duyệt', NOW(), NOW()),
    ('perm-id-absence-view', 'absence.view', 'Xem danh sách đơn xin phép vắng', 'Xem danh sách đơn xin phép vắng của lớp/buổi học', NOW(), NOW()),
    ('perm-id-absence-review', 'absence.review', 'Duyệt đơn xin phép vắng', 'Giảng viên duyệt đơn buổi học được phân công hoặc Quản lý đào tạo duyệt đơn', NOW(), NOW())
ON DUPLICATE KEY UPDATE 
    name = VALUES(name),
    description = VALUES(description),
    updated_at = NOW();

-- Phân quyền cho vai trò:
-- Học viên (trainee): absence.request
-- Giảng viên (trainer): absence.view, absence.review
-- Quản lý đào tạo (training_manager): absence.view, absence.review
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-trainee', 'perm-id-absence-request', NOW()),
    ('role-id-trainer', 'perm-id-absence-view', NOW()),
    ('role-id-trainer', 'perm-id-absence-review', NOW()),
    ('role-id-training-manager', 'perm-id-absence-view', NOW()),
    ('role-id-training-manager', 'perm-id-absence-review', NOW());
