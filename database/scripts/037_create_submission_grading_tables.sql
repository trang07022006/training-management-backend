-- Migration 037: Hệ thống Chấm điểm và Nhật ký Sửa điểm bài nộp (SCRUM-267)
-- Giảng viên chấm điểm và nhận xét cho bài nộp (speed grading)
-- Xem trước tệp nộp và mở link repo ngay trên màn hình chấm
-- Hỗ trợ nút chuyển nhanh sang bài kế tiếp
-- Điểm chỉ hiển thị cho học viên sau khi bấm Công bố
-- Mọi lần sửa điểm được ghi nhật ký (audit log)

-- 1. Bảng bài tập (assignments)
CREATE TABLE IF NOT EXISTS assignments (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    class_id VARCHAR(36) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NULL,
    max_score DECIMAL(5,2) NOT NULL DEFAULT 10.00,
    due_date DATETIME(6) NULL,
    is_published TINYINT(1) NOT NULL DEFAULT 0,
    published_at DATETIME(6) NULL,
    published_by VARCHAR(36) NULL,
    created_by VARCHAR(36) NOT NULL,
    is_deleted TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_asgn_class (class_id),
    INDEX idx_asgn_published (is_published),
    CONSTRAINT fk_asgn_class_267 FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE RESTRICT,
    CONSTRAINT fk_asgn_created_by_267 FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Bảng bài nộp của học viên (assignment_submissions)
CREATE TABLE IF NOT EXISTS assignment_submissions (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    assignment_id VARCHAR(36) NOT NULL,
    student_id VARCHAR(36) NOT NULL,
    submission_type VARCHAR(20) NOT NULL DEFAULT 'both', -- 'file', 'repo_url', 'both'
    file_url VARCHAR(500) NULL,
    file_name VARCHAR(255) NULL,
    file_size BIGINT NULL,
    repo_url VARCHAR(500) NULL,
    note TEXT NULL,
    submitted_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    status VARCHAR(20) NOT NULL DEFAULT 'submitted', -- 'submitted', 'graded', 'returned'
    score DECIMAL(5,2) NULL,
    feedback TEXT NULL,
    graded_by VARCHAR(36) NULL,
    graded_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_asgn_student (assignment_id, student_id),
    INDEX idx_sub_student (student_id),
    INDEX idx_sub_status (status),
    CONSTRAINT fk_sub_assignment FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,
    CONSTRAINT fk_sub_student FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE RESTRICT,
    CONSTRAINT fk_sub_graded_by FOREIGN KEY (graded_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Bảng nhật ký sửa điểm (submission_grade_audit_logs)
CREATE TABLE IF NOT EXISTS submission_grade_audit_logs (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    submission_id VARCHAR(36) NOT NULL,
    performed_by VARCHAR(36) NOT NULL,
    old_score DECIMAL(5,2) NULL,
    new_score DECIMAL(5,2) NOT NULL,
    old_feedback TEXT NULL,
    new_feedback TEXT NULL,
    change_reason VARCHAR(255) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_audit_sub (submission_id),
    INDEX idx_audit_perf (performed_by),
    CONSTRAINT fk_audit_submission FOREIGN KEY (submission_id) REFERENCES assignment_submissions(id) ON DELETE CASCADE,
    CONSTRAINT fk_audit_user FOREIGN KEY (performed_by) REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Phân quyền RBAC
INSERT INTO permissions (id, code, name, description, created_at, updated_at)
VALUES
    ('perm-id-sub-view',      'submission.view',      'Xem bài nộp học viên',    'Xem danh sách và chi tiết các bài nộp', NOW(), NOW()),
    ('perm-id-sub-grade',     'submission.grade',     'Chấm điểm bài nộp',       'Chấm điểm và ghi nhận xét bài nộp', NOW(), NOW()),
    ('perm-id-sub-publish',   'submission.publish',   'Công bố điểm bài tập',    'Công bố điểm bài nộp cho toàn lớp', NOW(), NOW()),
    ('perm-id-sub-view-own',  'submission.view_own',  'Xem bài nộp của bản thân', 'Học viên xem bài nộp và điểm đã công bố', NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), description = VALUES(description), updated_at = NOW();

INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES
    ('role-id-trainer',          'perm-id-sub-view',      NOW()),
    ('role-id-trainer',          'perm-id-sub-grade',     NOW()),
    ('role-id-trainer',          'perm-id-sub-publish',   NOW()),
    ('role-id-training-manager', 'perm-id-sub-view',      NOW()),
    ('role-id-training-manager', 'perm-id-sub-publish',   NOW()),
    ('role-id-trainee',          'perm-id-sub-view-own',  NOW());
