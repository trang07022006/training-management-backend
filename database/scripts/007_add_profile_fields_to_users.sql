-- Migration: 007_add_profile_fields_to_users.sql
-- Bổ sung trường date_of_birth và address cho bảng users (SCRUM-120)

ALTER TABLE users
ADD COLUMN date_of_birth DATE NULL AFTER phone,
ADD COLUMN address VARCHAR(255) NULL AFTER date_of_birth;
