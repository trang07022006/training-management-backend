-- Migration: SCRUM-46 Tạo bảng password_reset_tokens lưu trữ token đặt lại mật khẩu với thời hạn 30 phút
-- Bảng: password_reset_tokens
-- Mô tả:
--   - id: Khóa chính dạng UUID (VARCHAR(36))
--   - user_id: ID người dùng yêu cầu đặt lại mật khẩu (khóa ngoại tham chiếu users.id)
--   - token_hash: SHA-256 hash của reset token để bảo mật, tránh lưu plaintext token trong DB
--   - created_at: Thời điểm tạo token (UTC)
--   - expires_at: Thời điểm hết hạn của token (đúng 30 phút sau created_at)

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_reset_tokens_user_id (user_id),
    INDEX idx_reset_tokens_expires_at (expires_at)
);
