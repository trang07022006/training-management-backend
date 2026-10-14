-- Migration: 008_add_avatar_path_to_users.sql
-- Bổ sung trường avatar_path cho bảng users (SCRUM-121)

ALTER TABLE users
ADD COLUMN avatar_path VARCHAR(255) NULL AFTER address;
