-- Thêm cột must_change_password vào bảng users (SCRUM-215 Initial Password Change Request)
-- Giá trị mặc định là FALSE để không ảnh hưởng đến các tài khoản đã tồn tại.

ALTER TABLE users
ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE;
