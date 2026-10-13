-- Migration: 022_create_student_code_sequences_table.sql
-- SCRUM-215: Tự động sinh mã học viên an toàn concurrency (Sub-task 215-02)

CREATE TABLE IF NOT EXISTS student_code_sequences (
    prefix VARCHAR(20) NOT NULL PRIMARY KEY,
    current_val INT UNSIGNED NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
