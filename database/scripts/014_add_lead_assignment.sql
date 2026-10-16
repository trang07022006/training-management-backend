-- Migration: 014_add_lead_assignment.sql
-- SCRUM-127: Bổ sung trường phân công Lead (assigned_to_user_id, assigned_at) vào bảng leads

ALTER TABLE leads
ADD COLUMN assigned_to_user_id VARCHAR(36) NULL AFTER status,
ADD COLUMN assigned_at DATETIME NULL AFTER assigned_to_user_id;

ALTER TABLE leads
ADD CONSTRAINT fk_leads_assigned_user
    FOREIGN KEY (assigned_to_user_id)
    REFERENCES users(id)
    ON DELETE SET NULL
    ON UPDATE RESTRICT;

CREATE INDEX idx_leads_assigned_to_user_id ON leads (assigned_to_user_id);
