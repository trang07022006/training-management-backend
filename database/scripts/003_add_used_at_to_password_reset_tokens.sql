-- Migration: SCRUM-47 Thêm cột used_at đánh dấu token đặt lại mật khẩu đã sử dụng một lần
-- Bảng: password_reset_tokens
-- Mô tả:
--   - used_at: thời điểm token được sử dụng để đổi mật khẩu (NULL nếu chưa dùng)

ALTER TABLE password_reset_tokens
ADD COLUMN used_at DATETIME NULL DEFAULT NULL;
