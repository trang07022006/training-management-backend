-- Migration: 016_add_weight_and_learning_outcomes_to_subjects.sql
-- SCRUM-123: Bổ sung trường trọng số (weight) và mô tả chuẩn đầu ra (learning_outcomes) cho bảng subjects
-- Đảm bảo backward-compatible, nullable để an toàn cho dữ liệu hiện có trên MySQL 8.

ALTER TABLE `subjects`
    ADD COLUMN `weight` DECIMAL(6, 2) NULL DEFAULT NULL AFTER `total_sessions`,
    ADD COLUMN `learning_outcomes` TEXT NULL DEFAULT NULL AFTER `weight`;
