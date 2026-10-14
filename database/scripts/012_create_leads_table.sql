-- ==============================================================================
-- SCRUM-125: Nền tảng Đăng ký tư vấn công khai (Public Consultation / Leads)
-- Tạo bảng leads lưu trữ thông tin khách hàng tiềm năng gửi yêu cầu tư vấn
-- ==============================================================================

CREATE TABLE IF NOT EXISTS leads (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    phone VARCHAR(30) NOT NULL,
    email VARCHAR(255) NULL,
    interested_program_id VARCHAR(36) NULL,
    message TEXT NULL,
    source VARCHAR(50) NOT NULL DEFAULT 'public_form',
    status VARCHAR(50) NOT NULL DEFAULT 'new',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,

    CONSTRAINT fk_leads_interested_program
        FOREIGN KEY (interested_program_id)
        REFERENCES training_programs(id)
        ON DELETE SET NULL
        ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tạo index phục vụ tìm kiếm, phân loại và sắp xếp thời gian
CREATE INDEX idx_leads_status ON leads (status);
CREATE INDEX idx_leads_created_at ON leads (created_at);
CREATE INDEX idx_leads_interested_program_id ON leads (interested_program_id);
