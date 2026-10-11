-- Migration: 010_create_subjects_table.sql
-- Mô tả: Khởi tạo bảng danh mục môn học/học phần (SCRUM-123 - Activity A1)
-- Lưu ý: Bảng subjects là danh mục độc lập; quan hệ program_subjects thuộc SCRUM-124; buổi học thuộc SCRUM-129.

CREATE TABLE IF NOT EXISTS `subjects` (
    `id` VARCHAR(36) NOT NULL,
    `code` VARCHAR(50) NOT NULL,
    `name` VARCHAR(255) NOT NULL,
    `description` TEXT DEFAULT NULL,
    `credits` TINYINT UNSIGNED NOT NULL,
    `total_sessions` SMALLINT UNSIGNED DEFAULT NULL,
    `status` VARCHAR(50) NOT NULL DEFAULT 'draft',
    `created_at` DATETIME NOT NULL,
    `updated_at` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_subjects_code` (`code`),
    KEY `idx_subjects_status` (`status`),
    KEY `idx_subjects_created_at` (`created_at`),
    CONSTRAINT `chk_subjects_credits` CHECK (`credits` BETWEEN 1 AND 30),
    CONSTRAINT `chk_subjects_total_sessions` CHECK (`total_sessions` IS NULL OR `total_sessions` >= 0),
    CONSTRAINT `chk_subjects_status` CHECK (`status` IN ('draft', 'active', 'archived'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
