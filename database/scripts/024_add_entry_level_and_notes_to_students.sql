-- Migration: 024_add_entry_level_and_notes_to_students.sql
-- SCRUM-216: Quản lý hồ sơ học viên (Student Profile Management)
-- Thêm trường trình độ đầu vào (entry_level) và ghi chú (notes) cho học viên

ALTER TABLE students 
ADD COLUMN entry_level VARCHAR(255) NULL AFTER status,
ADD COLUMN notes TEXT NULL AFTER entry_level;
