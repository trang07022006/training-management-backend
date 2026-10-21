-- Migration 025: Bảng classes và class_subjects (SCRUM-217)
-- Quản lý mở lớp từ chương trình đào tạo, vòng đời lớp và danh sách môn học sao chép

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
    CONSTRAINT chk_classes_status CHECK (status IN ('preparing', 'in_progress', 'completed', 'cancelled')),
    CONSTRAINT chk_classes_max_capacity CHECK (max_capacity > 0),
    CONSTRAINT fk_classes_program FOREIGN KEY (program_id)
        REFERENCES training_programs(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    INDEX idx_classes_program_id (program_id),
    INDEX idx_classes_status (status),
    INDEX idx_classes_class_code (class_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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
    CONSTRAINT fk_class_subjects_class FOREIGN KEY (class_id)
        REFERENCES classes(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_class_subjects_subject FOREIGN KEY (subject_id)
        REFERENCES subjects(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    INDEX idx_class_subjects_class (class_id),
    INDEX idx_class_subjects_subject (subject_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
