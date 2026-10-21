-- Migration 036: Bảng assignments, assignment_submissions, submission_versions và submission_rework_requests (SCRUM-269)
-- Phục vụ nghiệp vụ giao bài, nộp bài, chấm điểm và quy trình Giảng viên yêu cầu học viên làm lại bài tập

CREATE TABLE IF NOT EXISTS assignments (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    class_id VARCHAR(36) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NULL,
    due_date DATETIME NULL,
    max_score DECIMAL(5,2) NOT NULL DEFAULT 10.00,
    status VARCHAR(50) NOT NULL DEFAULT 'published',
    created_by VARCHAR(36) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT fk_assignments_class FOREIGN KEY (class_id)
        REFERENCES classes(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_assignments_created_by FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    INDEX idx_assignments_class (class_id),
    INDEX idx_assignments_created_by (created_by),
    INDEX idx_assignments_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS assignment_submissions (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    assignment_id VARCHAR(36) NOT NULL,
    student_id VARCHAR(36) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'submitted',
    score DECIMAL(5,2) NULL,
    feedback TEXT NULL,
    graded_by VARCHAR(36) NULL,
    graded_at DATETIME NULL,
    rework_count INT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uq_assignment_student (assignment_id, student_id),
    CONSTRAINT fk_submissions_assignment FOREIGN KEY (assignment_id)
        REFERENCES assignments(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_submissions_student FOREIGN KEY (student_id)
        REFERENCES students(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_submissions_graded_by FOREIGN KEY (graded_by)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    INDEX idx_submissions_assignment (assignment_id),
    INDEX idx_submissions_student (student_id),
    INDEX idx_submissions_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS submission_rework_requests (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    submission_id VARCHAR(36) NOT NULL,
    submission_version_id VARCHAR(36) NULL,
    request_number INT UNSIGNED NOT NULL,
    comment TEXT NOT NULL,
    new_deadline DATETIME NOT NULL,
    requested_by VARCHAR(36) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'open',
    created_at DATETIME NOT NULL,
    fulfilled_at DATETIME NULL,
    fulfilled_version_id VARCHAR(36) NULL,
    UNIQUE KEY uq_sub_req_num (submission_id, request_number),
    CONSTRAINT fk_rework_submission FOREIGN KEY (submission_id)
        REFERENCES assignment_submissions(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_rework_requested_by FOREIGN KEY (requested_by)
        REFERENCES users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    INDEX idx_rework_sub_status (submission_id, status),
    INDEX idx_rework_requested_by (requested_by),
    INDEX idx_rework_new_deadline (new_deadline)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS submission_versions (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    submission_id VARCHAR(36) NOT NULL,
    version_number INT UNSIGNED NOT NULL,
    submission_type VARCHAR(50) NOT NULL DEFAULT 'text',
    content TEXT NULL,
    file_url VARCHAR(500) NULL,
    file_name VARCHAR(255) NULL,
    file_size INT UNSIGNED NULL,
    repo_url VARCHAR(500) NULL,
    submitted_at DATETIME NOT NULL,
    rework_request_id VARCHAR(36) NULL,
    UNIQUE KEY uq_sub_version (submission_id, version_number),
    CONSTRAINT fk_sub_versions_submission FOREIGN KEY (submission_id)
        REFERENCES assignment_submissions(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_sub_versions_rework FOREIGN KEY (rework_request_id)
        REFERENCES submission_rework_requests(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    INDEX idx_sub_versions_submission (submission_id),
    INDEX idx_sub_versions_rework (rework_request_id),
    INDEX idx_sub_versions_submitted_at (submitted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
