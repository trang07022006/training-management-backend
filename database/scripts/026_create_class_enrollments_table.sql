-- Migration 026: Bảng class_enrollments (SCRUM-218)
-- Quản lý ghi danh học viên vào lớp học (đơn lẻ và hàng loạt), chặn trùng và giới hạn sĩ số

CREATE TABLE IF NOT EXISTS class_enrollments (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    class_id VARCHAR(36) NOT NULL,
    student_id VARCHAR(36) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'enrolled',
    enrolled_at DATETIME NOT NULL,
    enrolled_by VARCHAR(36) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uq_class_student (class_id, student_id),
    CONSTRAINT fk_class_enrollments_class FOREIGN KEY (class_id)
        REFERENCES classes(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_class_enrollments_student FOREIGN KEY (student_id)
        REFERENCES students(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_class_enrollments_enrolled_by FOREIGN KEY (enrolled_by)
        REFERENCES users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    INDEX idx_enrollments_class_id (class_id),
    INDEX idx_enrollments_student_id (student_id),
    INDEX idx_enrollments_enrolled_at (enrolled_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
