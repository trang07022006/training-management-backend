-- Migration 036: Bảng chấm điểm theo Rubric nhiều tiêu chí (SCRUM-268)
-- Giảng viên khai báo rubric gồm các tiêu chí và trọng số (tổng = 100%)
-- Rubric lưu thành mẫu để dùng lại cho bài tập khác
-- Điểm tổng tính tự động từ điểm từng tiêu chí
-- Học viên thấy điểm chi tiết từng tiêu chí

-- ============================================================
-- 1. Bảng mẫu rubric (rubric_templates)
-- ============================================================
CREATE TABLE IF NOT EXISTS rubric_templates (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT NULL,
    created_by VARCHAR(36) NOT NULL,           -- FK -> users.id
    is_deleted TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_rt_created_by (created_by),
    INDEX idx_rt_is_deleted (is_deleted),
    CONSTRAINT fk_rt_created_by FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- 2. Bảng tiêu chí của rubric (rubric_criteria)
-- Tổng weight của các tiêu chí trong cùng 1 template = 100
-- ============================================================
CREATE TABLE IF NOT EXISTS rubric_criteria (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    template_id VARCHAR(36) NOT NULL,          -- FK -> rubric_templates.id
    name VARCHAR(255) NOT NULL,
    description TEXT NULL,
    max_score DECIMAL(5,2) NOT NULL DEFAULT 10.00,
    weight DECIMAL(5,2) NOT NULL,              -- Trọng số % (0 < weight <= 100)
    order_index INT NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_rc_template (template_id),
    CONSTRAINT fk_rc_template FOREIGN KEY (template_id) REFERENCES rubric_templates(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- 3. Bảng bài tập (assignments)
-- Giảng viên tạo bài tập, gắn rubric template để chấm điểm
-- ============================================================
CREATE TABLE IF NOT EXISTS assignments (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    class_id VARCHAR(36) NOT NULL,             -- FK -> classes.id
    title VARCHAR(255) NOT NULL,
    description TEXT NULL,
    rubric_template_id VARCHAR(36) NULL,       -- FK -> rubric_templates.id (NULL = chấm thủ công)
    max_score DECIMAL(5,2) NOT NULL DEFAULT 10.00,
    created_by VARCHAR(36) NOT NULL,           -- FK -> users.id
    is_deleted TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_asgn_class (class_id),
    INDEX idx_asgn_template (rubric_template_id),
    INDEX idx_asgn_created_by (created_by),
    CONSTRAINT fk_asgn_class FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE RESTRICT,
    CONSTRAINT fk_asgn_template FOREIGN KEY (rubric_template_id) REFERENCES rubric_templates(id) ON DELETE SET NULL,
    CONSTRAINT fk_asgn_created_by FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- 4. Bảng điểm tổng học viên (assignment_grades)
-- total_score tính tự động, NULL khi chưa chấm xong
-- ============================================================
CREATE TABLE IF NOT EXISTS assignment_grades (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    assignment_id VARCHAR(36) NOT NULL,        -- FK -> assignments.id
    student_id VARCHAR(36) NOT NULL,           -- FK -> students.id
    total_score DECIMAL(5,2) NULL,
    graded_by VARCHAR(36) NULL,                -- FK -> users.id
    graded_at DATETIME(6) NULL,
    feedback TEXT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_ag_assignment_student (assignment_id, student_id),
    INDEX idx_ag_student (student_id),
    CONSTRAINT fk_ag_assignment FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,
    CONSTRAINT fk_ag_student FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE RESTRICT,
    CONSTRAINT fk_ag_graded_by FOREIGN KEY (graded_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- 5. Bảng điểm từng tiêu chí (assignment_criteria_grades)
-- ============================================================
CREATE TABLE IF NOT EXISTS assignment_criteria_grades (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    grade_id VARCHAR(36) NOT NULL,             -- FK -> assignment_grades.id
    criteria_id VARCHAR(36) NOT NULL,          -- FK -> rubric_criteria.id
    score DECIMAL(5,2) NOT NULL,
    comment TEXT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_acg_grade_criteria (grade_id, criteria_id),
    INDEX idx_acg_grade (grade_id),
    CONSTRAINT fk_acg_grade FOREIGN KEY (grade_id) REFERENCES assignment_grades(id) ON DELETE CASCADE,
    CONSTRAINT fk_acg_criteria FOREIGN KEY (criteria_id) REFERENCES rubric_criteria(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- 6. Quyền hạn
-- ============================================================
INSERT INTO permissions (id, code, name, description, created_at, updated_at)
VALUES
    ('perm-id-rubric-manage',  'rubric.manage',  'Quản lý mẫu rubric',    'Tạo, sửa, xóa mẫu rubric', NOW(), NOW()),
    ('perm-id-rubric-view',    'rubric.view',    'Xem mẫu rubric',         'Xem danh sách và chi tiết mẫu rubric', NOW(), NOW()),
    ('perm-id-grade-manage',   'grade.manage',   'Chấm điểm học viên',     'Tạo bài tập và chấm điểm theo rubric', NOW(), NOW()),
    ('perm-id-grade-view-own', 'grade.view_own', 'Xem điểm của bản thân',  'Học viên xem điểm chi tiết từng tiêu chí', NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), description = VALUES(description), updated_at = NOW();

-- trainer: rubric.manage, rubric.view, grade.manage
-- training_manager: rubric.view, grade.manage
-- trainee: grade.view_own
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES
    ('role-id-trainer',          'perm-id-rubric-manage',  NOW()),
    ('role-id-trainer',          'perm-id-rubric-view',    NOW()),
    ('role-id-trainer',          'perm-id-grade-manage',   NOW()),
    ('role-id-training-manager', 'perm-id-rubric-view',    NOW()),
    ('role-id-training-manager', 'perm-id-grade-manage',   NOW()),
    ('role-id-trainee',          'perm-id-grade-view-own', NOW());
