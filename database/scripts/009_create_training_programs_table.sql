-- Migration: 009_create_training_programs_table.sql
-- SCRUM-122: Bảng training_programs quản lý chương trình đào tạo (Activity A1)
-- Lưu ý: Không tạo bảng liên kết program_subjects (thuộc phạm vi SCRUM-124).

CREATE TABLE IF NOT EXISTS training_programs (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT NULL,
    duration_semesters SMALLINT UNSIGNED NULL,
    standard_tuition_fee INT UNSIGNED NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT chk_training_programs_status CHECK (status IN ('draft', 'active', 'archived')),
    INDEX idx_training_programs_status (status),
    INDEX idx_training_programs_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
