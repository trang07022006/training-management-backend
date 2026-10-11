-- Migration: 019_create_lead_status_history.sql
-- SCRUM-213: Tạo bảng lưu lịch sử thay đổi trạng thái Lead (lead_status_history)
-- Đảm bảo toàn vẹn dữ liệu:
-- - Khi lead bị xóa -> CASCADE xóa lịch sử liên quan.
-- - Khi user bị xóa -> SET NULL người thực hiện để không mất vết lịch sử.

CREATE TABLE IF NOT EXISTS lead_status_history (
    id VARCHAR(36) PRIMARY KEY,
    lead_id VARCHAR(36) NOT NULL,
    old_status VARCHAR(50) NOT NULL,
    new_status VARCHAR(50) NOT NULL,
    reason VARCHAR(255) NULL,
    notes TEXT NULL,
    performed_by_user_id VARCHAR(36) NULL,
    created_at DATETIME NOT NULL,
    seq BIGINT AUTO_INCREMENT UNIQUE,
    CONSTRAINT fk_lsh_lead FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    CONSTRAINT fk_lsh_performed_user FOREIGN KEY (performed_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX idx_lsh_lead_id ON lead_status_history (lead_id);
CREATE INDEX idx_lsh_created_at ON lead_status_history (created_at);
