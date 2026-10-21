-- Migration: 013_create_subject_sessions_table.sql
-- Mô tả: Khởi tạo bảng quản lý buổi học của môn học (SCRUM-129 - Activity A1)
-- Mapping từ prototype: Lesson(STT, Topic, Objective, SubjectId) -> subject_sessions(session_number, topic, objective, subject_id)

CREATE TABLE IF NOT EXISTS `subject_sessions` (
    `id` VARCHAR(36) NOT NULL,
    `subject_id` VARCHAR(36) NOT NULL,
    `session_number` SMALLINT UNSIGNED NOT NULL,
    `topic` VARCHAR(255) NOT NULL,
    `objective` TEXT NOT NULL,
    `created_at` DATETIME NOT NULL,
    `updated_at` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_subject_sessions_number` (`subject_id`, `session_number`),
    KEY `idx_subject_sessions_subject_id` (`subject_id`),
    CONSTRAINT `chk_subject_sessions_number` CHECK (`session_number` >= 1),
    CONSTRAINT `fk_subject_sessions_subject` FOREIGN KEY (`subject_id`)
        REFERENCES `subjects` (`id`)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
