-- Migration: 006_add_name_phone_to_users.sql
-- Bổ sung trường name và phone cho bảng users (SCRUM-25)

ALTER TABLE users
ADD COLUMN name VARCHAR(255) NULL AFTER email,
ADD COLUMN phone VARCHAR(50) NULL AFTER name;
