-- Migration: SCRUM-34 Thêm các cột phục vụ khóa tạm thời 15 phút sau 5 lần đăng nhập sai
-- Bảng: users
-- Mô tả:
--   - failed_login_attempts: số lần đăng nhập sai liên tiếp (0-5)
--   - locked_until: thời điểm hết hạn khóa tạm thời (NULL nếu không bị khóa)

ALTER TABLE users
ADD COLUMN failed_login_attempts INT NOT NULL DEFAULT 0,
ADD COLUMN locked_until DATETIME NULL DEFAULT NULL;
