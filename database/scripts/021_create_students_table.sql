-- Migration: 021_create_students_table.sql
-- SCRUM-215: Chuyển Lead sang Hồ sơ học viên (Lead to Student)
-- Tạo bảng students lưu trữ thông tin học viên được chuyển đổi từ Lead

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

CREATE INDEX idx_students_status ON students (status);
CREATE INDEX idx_students_phone ON students (phone);
CREATE INDEX idx_students_email ON students (email);
