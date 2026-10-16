-- Migration 027: Bảng class_subject_instructors (SCRUM-220)
-- Phân công giảng viên chính và trợ giảng theo từng môn của lớp học

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
