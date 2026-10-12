-- Migration: 020_create_lead_care_logs.sql
-- SCRUM-214: Tạo bảng nhật ký chăm sóc Lead (lead_care_logs) và bổ sung callback_date vào bảng leads
-- Đảm bảo toàn vẹn dữ liệu:
-- - Khi lead bị xóa -> CASCADE xóa nhật ký liên quan.
-- - Khi user bị xóa -> SET NULL người thực hiện để không mất vết nhật ký.

CREATE TABLE IF NOT EXISTS lead_care_logs (
    id VARCHAR(36) PRIMARY KEY,
    lead_id VARCHAR(36) NOT NULL,
    interaction_type VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    interaction_at DATETIME NOT NULL,
    performed_by_user_id VARCHAR(36) NULL,
    created_at DATETIME NOT NULL,
    seq BIGINT AUTO_INCREMENT UNIQUE,
    CONSTRAINT fk_lcl_lead FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    CONSTRAINT fk_lcl_performed_user FOREIGN KEY (performed_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX idx_lcl_lead_id ON lead_care_logs (lead_id);
CREATE INDEX idx_lcl_interaction_at ON lead_care_logs (interaction_at);

-- Bổ sung trường callback_date (ngày nhắc gọi lại) cho Lead (SCRUM-214-02)
ALTER TABLE leads ADD COLUMN IF NOT EXISTS callback_date DATE NULL AFTER rejection_reason;
