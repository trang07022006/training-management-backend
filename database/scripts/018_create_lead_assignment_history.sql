-- Migration: 018_create_lead_assignment_history.sql
-- SCRUM-127: Tạo bảng lưu lịch sử chuyển giao / phân công Lead (lead_assignment_history)
-- Đảm bảo toàn vẹn dữ liệu:
-- - Khi lead bị xóa -> CASCADE xóa lịch sử liên quan.
-- - Khi user bị xóa -> SET NULL người phụ trách / người thực hiện để không mất lịch sử.

CREATE TABLE IF NOT EXISTS lead_assignment_history (
    id VARCHAR(36) PRIMARY KEY,
    lead_id VARCHAR(36) NOT NULL,
    old_assigned_to_user_id VARCHAR(36) NULL,
    new_assigned_to_user_id VARCHAR(36) NULL,
    performed_by_user_id VARCHAR(36) NULL,
    created_at DATETIME NOT NULL,
    seq BIGINT AUTO_INCREMENT UNIQUE,
    CONSTRAINT fk_lah_lead FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    CONSTRAINT fk_lah_old_user FOREIGN KEY (old_assigned_to_user_id) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_lah_new_user FOREIGN KEY (new_assigned_to_user_id) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_lah_performed_user FOREIGN KEY (performed_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX idx_lah_lead_id ON lead_assignment_history (lead_id);
CREATE INDEX idx_lah_created_at ON lead_assignment_history (created_at);
